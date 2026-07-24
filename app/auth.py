from itsdangerous import BadSignature, URLSafeSerializer


def sign_token(member_id: int, secret: str) -> str:
    return URLSafeSerializer(secret).dumps({"m": member_id})


def verify_token(token: str, secret: str):
    try:
        return URLSafeSerializer(secret).loads(token)["m"]
    except (BadSignature, KeyError, TypeError):
        return None
