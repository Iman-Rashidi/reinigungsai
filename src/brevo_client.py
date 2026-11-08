"""Brevo HTTPS API adapter. Supports DOI and draft-only campaigns, never sending."""
from __future__ import annotations
import html, json, re
from datetime import date
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class BrevoConfigurationError(ValueError): pass
class BrevoAPIError(RuntimeError): pass
EMAIL_RE=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

class BrevoClient:
    BASE_URL="https://api.brevo.com/v3"
    def __init__(self, *, api_key: str, timeout: int=12, opener=None):
        key=(api_key or "").strip()
        if len(key)<12 or any(c.isspace() for c in key): raise BrevoConfigurationError("BREVO_API_KEY fehlt oder ist ungültig.")
        if not 1<=timeout<=60: raise BrevoConfigurationError("API-Timeout muss 1 bis 60 Sekunden betragen.")
        self.api_key,self.timeout,self.opener=key,timeout,opener or urlopen
    def _request(self,method,path,payload=None):
        if not path.startswith("/") or "://" in path or ".." in path: raise BrevoConfigurationError("Ungültiger API-Pfad.")
        data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
        req=Request(self.BASE_URL+path,data=data,headers={"api-key":self.api_key,"Accept":"application/json","Content-Type":"application/json","User-Agent":"ReinigungsRadar/1.0"},method=method)
        try:
            with self.opener(req,timeout=self.timeout) as response: raw=response.read().decode()
        except HTTPError as exc:
            if exc.code in (401,403): raise BrevoAPIError("Brevo hat API-Schlüssel oder Berechtigungen abgelehnt.") from None
            if exc.code==429: raise BrevoAPIError("Brevo-API-Limit erreicht; später erneut versuchen.") from None
            raise BrevoAPIError(f"Brevo-Anfrage fehlgeschlagen (HTTP {exc.code}).") from None
        except (URLError,TimeoutError,OSError): raise BrevoAPIError("Brevo ist derzeit nicht erreichbar.") from None
        if not raw: return {}
        try: result=json.loads(raw)
        except json.JSONDecodeError: raise BrevoAPIError("Ungültige JSON-Antwort von Brevo.") from None
        if not isinstance(result,dict): raise BrevoAPIError("Unerwartetes Antwortformat von Brevo.")
        return result
    def get_lists(self):
        items=self._request("GET","/contacts/lists?limit=50&offset=0").get("lists")
        if not isinstance(items,list) or any(not isinstance(x,dict) for x in items): raise BrevoAPIError("Ungültige Listenübersicht.")
        return items
    def get_campaigns(self):
        items=self._request("GET","/emailCampaigns?limit=50&offset=0").get("campaigns")
        if not isinstance(items,list) or any(not isinstance(x,dict) for x in items): raise BrevoAPIError("Ungültige Kampagnenübersicht.")
        return items
    def create_doi_contact(self,*,email,first_name,list_id,template_id,redirection_url,consent_date,evidence_reference,consent_confirmed):
        email=(email or "").strip()
        if not EMAIL_RE.fullmatch(email): raise ValueError("Gültige E-Mail-Adresse eingeben.")
        if not consent_confirmed or not (evidence_reference or "").strip(): raise ValueError("Vorherige ausdrückliche Einwilligung samt Nachweisreferenz ist Pflicht.")
        try: day=date.fromisoformat(str(consent_date).strip()); lid=int(list_id); tid=int(template_id)
        except (ValueError,TypeError): raise ValueError("Datum sowie Listen- und Vorlagen-ID prüfen.") from None
        if day>date.today() or lid<1 or tid<1: raise ValueError("Datum darf nicht in der Zukunft liegen; IDs müssen positiv sein.")
        redir=urlsplit((redirection_url or "").strip())
        if redir.scheme!="https" or not redir.hostname or redir.username or redir.password: raise ValueError("DOI-Weiterleitung muss eine gültige HTTPS-URL sein.")
        attrs={"FNAME":(first_name or "").strip()} if (first_name or "").strip() else {}
        return self._request("POST","/contacts/doubleOptinConfirmation",{"email":email,"includeListIds":[lid],"templateId":tid,"redirectionUrl":redirection_url.strip(),"attributes":attrs,"contactPixelTrackingConsent":False})
    def create_campaign_draft(self,*,name,subject,sender_email,sender_name,list_ids,body,preview_text="",audience_consent_confirmed,audience_evidence_reference):
        name=(name or "").strip(); subject=(subject or "").strip(); sender_email=(sender_email or "").strip(); sender_name=(sender_name or "").strip(); body=(body or "").strip()
        if not name or not subject or not sender_name or not body: raise ValueError("Name, Betreff, Absendername und Inhalt sind Pflichtfelder.")
        if not EMAIL_RE.fullmatch(sender_email): raise ValueError("Verifizierte Absenderadresse eingeben.")
        if not audience_consent_confirmed or not (audience_evidence_reference or "").strip(): raise ValueError("Einwilligungsnachweis für alle Zielgruppen bestätigen und referenzieren.")
        try: ids=sorted({int(x) for x in list_ids})
        except (ValueError,TypeError): raise ValueError("Ungültige Zielgruppen.") from None
        if not ids or any(x<1 for x in ids): raise ValueError("Mindestens eine gültige Zielgruppe auswählen.")
        if len(name)>200 or len(subject)>500 or len(body)>100000 or len(preview_text)>500: raise ValueError("Feldlänge überschritten.")
        safe=html.escape(body).replace("\r\n","\n").replace("\n","<br>\n")
        content="<!doctype html><html><body><div>"+safe+"</div><p>Sie erhalten diese Nachricht aufgrund einer dokumentierten Einwilligung. Abmelden können Sie sich über den in Brevo eingefügten Abmeldelink.</p></body></html>"
        payload={"name":name,"subject":subject,"sender":{"name":sender_name,"email":sender_email},"recipients":{"listIds":ids},"htmlContent":content,"previewText":(preview_text or "").strip()}
        return self._request("POST","/emailCampaigns",payload)
