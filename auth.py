"""Dashboard account-to-station access mapping.

Passwords may be changed through the matching Render environment variables
without editing source code.  ``device=None`` grants access to all stations.
"""
import os


ACCOUNTS = {
    "pub1": {"password": os.environ.get("PUB1_PASSWORD", r"KNF-1"), "device": "KNF-B452BF260717021"}, #User: pub1, Password: Wt@1682-1
    "pub2": {"password": os.environ.get("PUB2_PASSWORD", r"KWRP-2"), "device": "KWRP-B452BF260731002"},
    "pub3": {"password": os.environ.get("PUB3_PASSWORD", r"JWRP-3"), "device": "JWRP-B452BF260731009"},
    "pub4": {"password": os.environ.get("PUB4_PASSWORD", r"UPWRP-4"), "device": "UPWRP-B452BF260731003"},
    "pub5": {"password": os.environ.get("PUB5_PASSWORD", r"CWRP-5"), "device": "CWRP-B452BF260717023"},
    "admin": {"password": os.environ.get("ADMIN_PASSWORD", "admin123"), "device": None},
}
