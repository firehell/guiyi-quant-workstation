import os


def create_tqsdk_api():
    from tqsdk import TqApi, TqAuth

    username = os.getenv("TQSDK_USERNAME")
    password = os.getenv("TQSDK_PASSWORD")
    if not username or not password:
        raise RuntimeError("TQSDK_USERNAME and TQSDK_PASSWORD are required for TqSdk downloads")
    return TqApi(auth=TqAuth(username, password))
