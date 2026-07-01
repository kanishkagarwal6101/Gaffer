"""Quick slugify sanity check for viz PNG filenames (M7 hardening)."""

from __future__ import annotations

from app.viz.pitch import slugify


def main() -> None:
    cases = {
        "N'Golo Kanté": "n-golo-kante",
        "Kylian Mbappé Lottin — shot map": "kylian-mbappe-lottin-shot-map",
        "Junior/Jr.": "junior-jr",
        "France vs Argentina — pass network": "france-vs-argentina-pass-network",
    }
    for raw, expected in cases.items():
        got = slugify(raw)
        assert got == expected, f"{raw!r}: expected {expected!r}, got {got!r}"
        print(f"PASS  {raw!r} -> {got}")
    print("\nALL PASS")


if __name__ == "__main__":
    main()
