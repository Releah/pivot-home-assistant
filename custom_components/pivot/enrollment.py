"""One-time encrypted enrollment. Private key stays in the HA flow process."""
import base64
import hashlib
import json
import re


def generate_enrollment():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = key.public_key()
    pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    fingerprint = hashlib.sha256(public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    return key, pem, fingerprint


def decrypt_enrollment(key, fingerprint, text):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    if not isinstance(text, str) or len(text) > 8192:
        raise ValueError('invalid_envelope')
    envelope = json.loads(text)
    if set(envelope) != {'installationId', 'fingerprint', 'ciphertext'} or envelope['fingerprint'] != fingerprint:
        raise ValueError('invalid_envelope')
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', envelope['installationId']):
        raise ValueError('invalid_envelope')
    value = envelope['ciphertext']
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{512}', value):
        raise ValueError('invalid_envelope')
    ciphertext = base64.urlsafe_b64decode(value)
    credential = key.decrypt(ciphertext, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)).decode()
    if not re.fullmatch(r'hi1\.[A-Za-z0-9_-]{43}', credential):
        raise ValueError('invalid_envelope')
    return credential
