"""Read-only NP Notes GitHub connectivity diagnostic.

No note data, no credential file content and no token is printed. Tests Python
HTTPS connectivity to public GitHub API endpoint. Authenticated application
connectivity is tested separately by its private-repository probe.
"""
import socket
import ssl
import sys
import urllib.error
import urllib.request

def main():
    print("PYTHON_VERSION=" + sys.version.split()[0])
    print("TLS_OPENSSL=" + ssl.OPENSSL_VERSION.split()[0])
    print("NOTES_ACCESSED=FALSE")
    print("TOKEN_ACCESSED=FALSE")
    try:
        resolved = socket.getaddrinfo("api.github.com", 443, type=socket.SOCK_STREAM)
        print("GITHUB_DNS=" + ("PASS" if resolved else "FAIL"))
    except Exception as e:
        print("GITHUB_DNS=FAIL")
        print("DNS_ERROR_TYPE=" + type(e).__name__)
    req = urllib.request.Request(
        "https://api.github.com/repos/Nikita-Postnov/CODE",
        headers={"User-Agent": "NPNotes-Connectivity-Diagnostic",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            print("GITHUB_PUBLIC_API=HTTP_" + str(response.status))
    except urllib.error.HTTPError as e:
        print("GITHUB_PUBLIC_API=HTTP_" + str(e.code))
    except Exception as e:
        print("GITHUB_PUBLIC_API=FAILED")
        print("HTTPS_ERROR_TYPE=" + type(e).__name__)

if __name__ == "__main__":
    main()
