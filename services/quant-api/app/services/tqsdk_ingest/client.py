import os


def create_tqsdk_api():
    from tqsdk import TqApi, TqAuth

    username = os.getenv("TQ_USERNAME") or os.getenv("TQSDK_USERNAME")
    password = os.getenv("TQ_PASSWORD") or os.getenv("TQSDK_PASSWORD")
    if not username or not password:
        raise RuntimeError("TQ_USERNAME/TQ_PASSWORD or TQSDK_USERNAME/TQSDK_PASSWORD are required for TqSdk downloads")
    return TqApi(auth=TqAuth(username, password))
