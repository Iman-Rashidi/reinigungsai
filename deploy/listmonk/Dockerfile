FROM listmonk/listmonk:v6.2.0

ENV TZ=Europe/Berlin

# Keep the upstream docker-entrypoint (non-root user handling and *_FILE
# secret loading), run DB installation/upgrades idempotently, then bind to
# Render's injected PORT. Render's free filesystem is ephemeral: uploads are
# not persistent unless a paid persistent disk or external object store is used.
CMD ["sh", "-c", "./listmonk --install --idempotent --yes --config '' && ./listmonk --upgrade --yes --config '' && export LISTMONK_app__address=\"0.0.0.0:${PORT:-10000}\" && ./listmonk --config ''"]
