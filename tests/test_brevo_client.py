import json, unittest
from datetime import date
from urllib.error import HTTPError
from src.brevo_client import BrevoAPIError, BrevoClient, BrevoConfigurationError
class Resp:
 def __init__(self,p): self.raw=json.dumps(p).encode() if not isinstance(p,bytes) else p
 def __enter__(self): return self
 def __exit__(self,*a): return False
 def read(self): return self.raw
class Open:
 def __init__(self,*p): self.p=list(p); self.requests=[]
 def __call__(self,r,timeout):
  self.requests.append((r,timeout)); x=self.p.pop(0)
  if isinstance(x,Exception): raise x
  return Resp(x)
class Tests(unittest.TestCase):
 def c(self,o): return BrevoClient(api_key="k"*40,opener=o)
 def test_key_required(self):
  with self.assertRaises(BrevoConfigurationError): BrevoClient(api_key="")
 def test_get_lists(self):
  o=Open({"lists":[{"id":1}]}); self.assertEqual(self.c(o).get_lists()[0]["id"],1)
 def test_get_campaigns(self):
  o=Open({"campaigns":[{"id":3}]}); self.assertEqual(self.c(o).get_campaigns()[0]["id"],3)
 def test_doi_requires_consent_and_proof(self):
  o=Open({})
  with self.assertRaises(ValueError): self.c(o).create_doi_contact(email="a@b.test",first_name="",list_id=1,template_id=2,redirection_url="https://a.test",consent_date=date.today().isoformat(),evidence_reference="",consent_confirmed=True)
  self.assertEqual(o.requests,[])
 def test_doi_endpoint(self):
  o=Open({"message":"ok"})
  self.c(o).create_doi_contact(email="a@b.test",first_name="A",list_id=1,template_id=2,redirection_url="https://a.test/ok",consent_date=date.today().isoformat(),evidence_reference="proof",consent_confirmed=True)
  req,_=o.requests[0]; p=json.loads(req.data.decode())
  self.assertIn("/contacts/doubleOptinConfirmation",req.full_url); self.assertEqual(p["includeListIds"],[1])
 def test_doi_rejects_http_and_future_date(self):
  o=Open({}); c=self.c(o); kw=dict(email="a@b.test",first_name="",list_id=1,template_id=2,redirection_url="http://a.test",consent_date=date.today().isoformat(),evidence_reference="proof",consent_confirmed=True)
  with self.assertRaises(ValueError): c.create_doi_contact(**kw)
  kw["redirection_url"]="https://a.test"; kw["consent_date"]="2999-01-01"
  with self.assertRaises(ValueError): c.create_doi_contact(**kw)
  self.assertEqual(o.requests,[])
 def test_campaign_requires_consent(self):
  o=Open({})
  with self.assertRaises(ValueError): self.c(o).create_campaign_draft(name="n",subject="s",sender_email="a@b.test",sender_name="A",list_ids=[1],body="x",audience_consent_confirmed=False,audience_evidence_reference="")
  self.assertEqual(o.requests,[])
 def test_campaign_draft_escapes_html_and_never_schedules(self):
  o=Open({"id":9}); r=self.c(o).create_campaign_draft(name="n",subject="s",sender_email="a@b.test",sender_name="A",list_ids=[2,1],body="<script>x</script>",audience_consent_confirmed=True,audience_evidence_reference="ref")
  req,_=o.requests[0]; p=json.loads(req.data.decode())
  self.assertEqual(r["id"],9); self.assertEqual(p["recipients"]["listIds"],[1,2]); self.assertNotIn("<script>",p["htmlContent"]); self.assertNotIn("scheduledAt",p)
 def test_auth_failure_hides_key(self):
  o=Open(HTTPError("https://api.brevo.com",401,"No",None,None))
  with self.assertRaises(BrevoAPIError) as ctx: self.c(o).get_lists()
  self.assertNotIn("k"*40,str(ctx.exception))
 def test_no_send_method(self):
  self.assertFalse(hasattr(BrevoClient,"send_campaign")); self.assertFalse(hasattr(BrevoClient,"schedule_campaign"))
if __name__=="__main__": unittest.main()
