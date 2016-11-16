from django.utils.six.moves.urllib.parse import urlparse


PROTOCOL_TO_PORT = {
    'http': 80,
    'https': 443,
}

def same_origin(url1, url2):
    """
    Checks if two URLs are 'same-origin'
    """
    p1, p2 = urlparse(url1), urlparse(url2)
    try:
        o1 = (p1.scheme, p1.hostname, p1.port or PROTOCOL_TO_PORT[p1.scheme])
        o2 = (p2.scheme, p2.hostname, p2.port or PROTOCOL_TO_PORT[p2.scheme])
        return o1 == o2
    except (ValueError, KeyError):
        return False
