#!/usr/bin/env python3
"""
HOMELAB — Generate docker-compose stacks for AI development.
Ollama, Open WebUI, Flowise, n8n, Jupyter, Weaviate, Qdrant, monitoring.

Usage:
  homelab generate                    Interactive stack builder
  homelab quick                       Quick-start: Ollama + WebUI
  homelab list                        Show available services
  homelab serve "stack.yml"           Validate and serve config
"""

def dump_compose(stack: dict) -> str:
    """Serialize docker-compose dict to YAML-like text (no deps)."""
    lines = ['version: "3.8"', f'name: "{stack.get("name", "homelab")}"', "", "services:"]
    
    for name, svc in stack.get("services", {}).items():
        lines.append(f"  {name}:")
        lines.append(f'    image: {svc["image"]}')
        lines.append(f'    container_name: {name}')
        lines.append(f'    restart: unless-stopped')
        lines.append(f"    networks:")
        lines.append(f"      - homelab")
        
        if svc.get("ports"):
            lines.append(f"    ports:")
            for p in svc["ports"]:
                lines.append(f'      - "{p}"')
        
        if svc.get("volumes"):
            lines.append(f"    volumes:")
            for v in svc["volumes"]:
                lines.append(f'      - {v}')
        
        if svc.get("environment"):
            lines.append(f"    environment:")
            for k, v in svc["environment"].items():
                lines.append(f'      {k}: "{v}"')
        
        if svc.get("depends_on"):
            lines.append(f"    depends_on:")
            for d in svc["depends_on"]:
                lines.append(f"      {d}:")
                lines.append(f"        condition: service_started")
        
        if svc.get("deploy"):
            lines.append(f"    deploy:")
            lines.append(f"      resources:")
            lines.append(f"        reservations:")
            lines.append(f"          devices:")
            lines.append(f'            - driver: nvidia')
            lines.append(f"              count: 1")
            lines.append(f"              capabilities: [gpu]")
        
        lines.append("")
    
    lines.append("networks:")
    lines.append("  homelab:")
    lines.append("    driver: bridge")
    
    return "\n".join(lines)


def parse_compose(content: str) -> dict:
    """Simple YAML-like parser for validation (no deps)."""
    services = {}
    current_service = None
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if line.startswith("  ") and not line.startswith("    ") and ":" in stripped and not stripped.startswith("-"):
            name = stripped.rstrip(":").strip()
            if name not in ("services", "networks", "volumes", "environment", "ports", "deploy", "depends_on", "resources", "reservations", "devices"):
                current_service = name
                services[name] = {}
        elif line.startswith("    image:") and current_service:
            services[current_service]["image"] = stripped.split(":", 1)[1].strip()
    return {"services": services}

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

SERVICES = {
    "ollama": {
        "image": "ollama/ollama:latest",
        "ports": ["11434:11434"],
        "volumes": ["./ollama:/root/.ollama"],
        "gpu": True,
        "desc": "Local LLM inference (llama.cpp, GGUF models)",
        "ram": "4GB+",
        "cpu": 4,
    },
    "open-webui": {
        "image": "ghcr.io/open-webui/open-webui:main",
        "ports": ["3000:8080"],
        "volumes": ["./open-webui:/app/backend/data"],
        "env": {"OLLAMA_BASE_URL": "http://ollama:11434"},
        "depends": ["ollama"],
        "desc": "ChatGPT-like UI for Ollama",
        "ram": "2GB",
        "cpu": 2,
    },
    "flowise": {
        "image": "flowiseai/flowise:latest",
        "ports": ["3001:3000"],
        "volumes": ["./flowise:/root/.flowise"],
        "desc": "Low-code LLM flow builder",
        "ram": "1GB",
        "cpu": 2,
    },
    "n8n": {
        "image": "n8nio/n8n:latest",
        "ports": ["5678:5678"],
        "volumes": ["./n8n:/home/node/.n8n"],
        "desc": "Workflow automation",
        "ram": "1GB",
        "cpu": 2,
    },
    "jupyter": {
        "image": "jupyter/scipy-notebook:latest",
        "ports": ["8888:8888"],
        "volumes": ["./notebooks:/home/jovyan/work"],
        "env": {"JUPYTER_TOKEN": "homelab"},
        "desc": "Python data science notebooks",
        "ram": "2GB",
        "cpu": 2,
    },
    "weaviate": {
        "image": "semitechnologies/weaviate:latest",
        "ports": ["8080:8080"],
        "volumes": ["./weaviate:/var/lib/weaviate"],
        "env": {
            "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED": "true",
            "PERSISTENCE_DATA_PATH": "/var/lib/weaviate",
            "DEFAULT_VECTORIZER_MODULE": "none",
            "CLUSTER_HOSTNAME": "node1",
        },
        "desc": "Vector database for RAG",
        "ram": "2GB",
        "cpu": 2,
    },
    "qdrant": {
        "image": "qdrant/qdrant:latest",
        "ports": ["6333:6333", "6334:6334"],
        "volumes": ["./qdrant:/qdrant/storage"],
        "desc": "Vector search engine",
        "ram": "1GB",
        "cpu": 2,
    },
    "langfuse": {
        "image": "langfuse/langfuse:latest",
        "ports": ["3002:3000"],
        "env": {
            "DATABASE_URL": "postgresql://langfuse:langfuse@postgres:5432/langfuse",
            "NEXTAUTH_SECRET": "changeme",
            "SALT": "changeme",
        },
        "depends": ["postgres"],
        "desc": "LLM observability & tracing",
        "ram": "1GB",
        "cpu": 2,
    },
    "postgres": {
        "image": "postgres:16-alpine",
        "ports": [],
        "volumes": ["./postgres:/var/lib/postgresql/data"],
        "env": {"POSTGRES_USER": "langfuse", "POSTGRES_PASSWORD": "langfuse", "POSTGRES_DB": "langfuse"},
        "desc": "PostgreSQL (for Langfuse)",
        "ram": "256MB",
        "cpu": 1,
    },
    "portainer": {
        "image": "portainer/portainer-ce:latest",
        "ports": ["9443:9443"],
        "volumes": ["./portainer:/data", "/var/run/docker.sock:/var/run/docker.sock"],
        "desc": "Docker management UI",
        "ram": "256MB",
        "cpu": 1,
    },
    "prometheus": {
        "image": "prom/prometheus:latest",
        "ports": ["9090:9090"],
        "volumes": ["./prometheus.yml:/etc/prometheus/prometheus.yml", "./prometheus:/prometheus"],
        "desc": "Metrics & monitoring",
        "ram": "1GB",
        "cpu": 2,
    },
    "grafana": {
        "image": "grafana/grafana:latest",
        "ports": ["3003:3000"],
        "volumes": ["./grafana:/var/lib/grafana"],
        "desc": "Dashboards & alerts",
        "ram": "512MB",
        "cpu": 2,
    },
}


def generate_stack(selected: list) -> dict:
    """Build docker-compose config for selected services."""
    stack = {
        "version": "3.8",
        "name": "homelab-ai",
        "services": {},
        "networks": {"homelab": {"driver": "bridge"}},
    }
    
    total_ram = 0
    total_cpu = 0
    has_gpu = False
    
    for name in selected:
        svc = SERVICES[name]
        conf = {
            "image": svc["image"],
            "container_name": name,
            "restart": "unless-stopped",
            "networks": ["homelab"],
        }
        
        if svc.get("ports") and svc["ports"]:
            conf["ports"] = svc["ports"]
        
        if svc.get("volumes"):
            conf["volumes"] = svc["volumes"]
        
        if svc.get("env"):
            conf["environment"] = svc["env"]
        
        if svc.get("depends"):
            conf["depends_on"] = {d: {"condition": "service_started"} for d in svc["depends"]}
        
        if svc.get("gpu"):
            conf["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [{"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}]
                    }
                }
            }
            has_gpu = True
        
        stack["services"][name] = conf
        
        ram_str = svc.get("ram", "0GB")
        ram_gb = float(ram_str.replace("GB", "").replace("MB", "").replace("+", ""))
        if "MB" in ram_str:
            ram_gb /= 1024
        total_ram += ram_gb
        total_cpu += svc.get("cpu", 1)
    
    return stack, total_ram, total_cpu, has_gpu


def cmd_generate(args) -> None:
    """Interactive stack builder."""
    if args.quick:
        selected = ["ollama", "open-webui", "portainer"]
    else:
        print("\n🧪 Homelab AI Stack Builder\n")
        print("Select services (comma-separated, or 'all'):\n")
        for name, svc in SERVICES.items():
            gpu = " [GPU]" if svc.get("gpu") else ""
            print(f"  {name:<14} {svc['desc']}{gpu}  ({svc.get('ram','?')})")
        
        choice = input(f"\nServices> ").strip()
        
        if choice.lower() == "all":
            selected = list(SERVICES.keys())
        else:
            selected = [s.strip() for s in choice.split(",") if s.strip() in SERVICES]
        
        if not selected:
            print("❌ No valid services selected.")
            sys.exit(1)
    
    stack, ram, cpu, gpu = generate_stack(selected)
    
    # Write docker-compose.yml
    path = Path(args.output or "docker-compose.yml")
    path.write_text(dump_compose(stack))
    
    print(f"\n✅ Generated {path}")
    print(f"\n📦 Stack: {', '.join(selected)}")
    print(f"   Services: {len(selected)}")
    print(f"   Est. RAM:  {ram:.1f} GB")
    print(f"   Est. CPU:  {cpu} cores")
    if gpu:
        print(f"   GPU:      Required (NVIDIA)")
    print(f"\n   Start:    docker compose up -d")
    print(f"   Stop:     docker compose down")
    
    # Print URLs
    print(f"\n   URLs:")
    for name in selected:
        svc = SERVICES[name]
        for port in svc.get("ports", []):
            host_port = port.split(":")[0]
            protocol = "https" if "443" in host_port else "http"
            print(f"   {name:<14} {protocol}://localhost:{host_port}")


def cmd_list(args) -> None:
    """List available services."""
    print(f"\n📋 Available Services ({len(SERVICES)}):\n")
    for name, svc in SERVICES.items():
        gpu = " 🎮GPU" if svc.get("gpu") else ""
        print(f"  {name:<14} {svc['desc']}{gpu}")
        print(f"              RAM: {svc.get('ram','?')} | CPU: {svc.get('cpu','?')} cores")
        if svc.get("depends"):
            print(f"              Requires: {', '.join(svc['depends'])}")
        print()


def cmd_serve(args) -> None:
    """Validate docker-compose file."""
    path = Path(args.file)
    if not path.exists():
        print(f"❌ File not found: {args.file}")
        sys.exit(1)
    
    try:
        config = parse_compose(path.read_text())
        services = config.get("services", {})
        print(f"\n✅ Valid config: {len(services)} services")
        
        total_ram = 0
        for name, svc_config in services.items():
            if name in SERVICES:
                ram = float(SERVICES[name].get("ram", "0GB").replace("GB", "").replace("MB", ""))
                if "MB" in SERVICES[name].get("ram", ""):
                    ram /= 1024
                total_ram += ram
            print(f"   {name}")
        
        print(f"\n   Est. total RAM: {total_ram:.1f} GB")
        print(f"   Start: docker compose -f {args.file} up -d")
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML: {e}")


def main():
    parser = argparse.ArgumentParser(description="Homelab — AI dev platform stack generator")
    sub = parser.add_subparsers(dest="command")
    
    gen_p = sub.add_parser("generate")
    gen_p.add_argument("--quick", action="store_true", help="Quick-start: Ollama + WebUI")
    gen_p.add_argument("-o", "--output", default="docker-compose.yml", help="Output file")
    
    sub.add_parser("list")
    
    serve_p = sub.add_parser("serve")
    serve_p.add_argument("file", help="docker-compose.yml to validate")
    
    args = parser.parse_args()
    
    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
