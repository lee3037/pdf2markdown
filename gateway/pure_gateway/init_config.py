"""Create a local token once, without printing or replacing an existing configuration."""
import secrets

from .config import ROOT


def main():
    destination = ROOT / ".env"
    if destination.exists():
        print("Existing gateway .env preserved.")
        return
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    with destination.open("x", encoding="utf-8") as output:
        output.write(content.replace("REPLACE_WITH_A_RANDOM_TOKEN_OF_AT_LEAST_32_CHARS", secrets.token_urlsafe(32)))
    print("Created gateway .env; token is not printed.")


if __name__ == "__main__":
    main()
