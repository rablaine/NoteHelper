"""
Run the AI gateway locally against real Azure OpenAI.

Loads config from the ARM template defaults so you don't have to set
env vars manually. Uses your local `az login` credential.

Usage:
    python infra/gateway/run_local.py          # port 8000
    python infra/gateway/run_local.py --port 8080
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_arm_defaults() -> dict[str, str]:
    """Read default parameter values from app-service.json."""
    arm_path = os.path.join(SCRIPT_DIR, "app-service.json")
    with open(arm_path) as f:
        template = json.load(f)
    params = template.get("parameters", {})
    return {
        "AZURE_OPENAI_ENDPOINT": params["openaiEndpoint"]["defaultValue"],
        "AZURE_OPENAI_DEPLOYMENT": params["openaiDeployment"]["defaultValue"],
        "AZURE_OPENAI_CONNECT_DEPLOYMENT": params["openaiConnectDeployment"]["defaultValue"],
        "AZURE_OPENAI_API_VERSION": params["openaiApiVersion"]["defaultValue"],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run NoteHelper AI gateway locally")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    args = parser.parse_args()

    # Set env vars from ARM defaults (don't overwrite if already set)
    defaults = _load_arm_defaults()
    for key, value in defaults.items():
        if key not in os.environ:
            os.environ[key] = value
            print(f"  {key}={value}")
        else:
            print(f"  {key}={os.environ[key]}  (from environment)")

    # Add gateway directory to path so imports work
    sys.path.insert(0, SCRIPT_DIR)

    # Import and run the Flask app
    from gateway import app  # noqa: E402
    print(f"\nStarting gateway on http://localhost:{args.port}")
    print("Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=args.port, debug=True)


if __name__ == "__main__":
    main()
