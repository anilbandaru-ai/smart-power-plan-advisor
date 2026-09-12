import json
import os
import tempfile


def publish(settings, manifest, records, providers):
    """An interrupted upsert must not replace the last usable corpus manifest."""
    providers.upsert(records, manifest["namespace"])
    settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=settings.manifest_path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, settings.manifest_path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
