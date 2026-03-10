"""
Quick connectivity check for Azure OpenAI deployments.

Uses your local `az login` credential to hit each deployment with a
trivial prompt. Run this before deploying gateway changes to verify
that all deployments are reachable and responding.

Usage:
    python infra/gateway/validate_deployments.py
"""
import sys

from azure.identity import AzureCliCredential, DefaultAzureCredential
from openai import AzureOpenAI

ENDPOINT = "https://sharednotehelperendpoints.cognitiveservices.azure.com/"
API_VERSION = "2025-01-01-preview"

DEPLOYMENTS = {
    "gpt-4o-mini": "Default (milestone matching, topic suggestion, etc.)",
    "gpt-5.3-chat": "Connect evaluations (evidence scaffolding)",
}


def _get_client() -> AzureOpenAI:
    """Build an AzureOpenAI client using local credentials."""
    try:
        cred = AzureCliCredential()
        cred.get_token("https://cognitiveservices.azure.com/.default")
    except Exception:
        cred = DefaultAzureCredential()

    from azure.identity import get_bearer_token_provider
    token_provider = get_bearer_token_provider(
        cred, "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=ENDPOINT,
        azure_ad_token_provider=token_provider,
    )


def main():
    print(f"Endpoint: {ENDPOINT}")
    print(f"API version: {API_VERSION}\n")

    client = _get_client()
    all_ok = True

    for deployment, description in DEPLOYMENTS.items():
        print(f"  {deployment} — {description}")
        print(f"    Sending test prompt... ", end="", flush=True)
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say 'OK' and nothing else."},
                ],
                max_tokens=5,
                temperature=0,
            )
            text = (response.choices[0].message.content or "").strip()
            model = response.model or deployment
            tokens = response.usage.total_tokens if response.usage else "?"
            print(f"OK  (model={model}, tokens={tokens}, response='{text}')")
        except Exception as exc:
            print(f"FAILED\n    Error: {exc}")
            all_ok = False
        print()

    if all_ok:
        print("All deployments responding.")
    else:
        print("One or more deployments failed — check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
