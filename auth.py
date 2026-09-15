"""Dashboard account-to-station access mapping.

Passwords may be changed through the matching Render environment variables
without editing source code.  ``device=None`` grants access to all stations.
"""
import os


ACCOUNTS = {
    "pub1": {"password": os.environ.get("PUB1_PASSWORD", r"Wt@1682-1"), "device": "TG452-01"}, #User: pub1, Password: Wt@1682-1
    "pub2": {"password": os.environ.get("PUB2_PASSWORD", r"Wt@1682-2"), "device": "TG452-02"},
    "pub3": {"password": os.environ.get("PUB3_PASSWORD", r"Wt@1682-3"), "device": "TG452-03"},
    "pub4": {"password": os.environ.get("PUB4_PASSWORD", r"Wt@1682-4"), "device": "TG452-04"},
    "pub5": {"password": os.environ.get("PUB5_PASSWORD", r"Wt@1682-5"), "device": "TG452-05"},
    "admin": {"password": os.environ.get("ADMIN_PASSWORD", "admin123"), "device": None},
}
