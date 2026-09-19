"""Seed demo data into the mini-CRM. Usage: python -m targets.crm.seed."""

from targets.crm.app import seed

if __name__ == "__main__":
    print(seed())
