"""Discover public Simplon projects, copy GitLab branches/tags, and refresh profile.

Run in Hajar-Simplon/.github with PORTFOLIO_TOKEN in the environment.
Never deletes refs or force-pushes. Existing divergent mirrors fail visibly.
"""
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ORG = 'Hajar-Simplon'
USER = 'hajarmezouar'
TOKEN = os.environ['PORTFOLIO_TOKEN']
DESCRIPTIONS = {
    "kube-operator-manager": "AKS observability with Prometheus Operator, Grafana, cert-manager, HTTPS ingress, and alerts.",
    "tp-aks-prometheus-grafana": "AKS monitoring with raw Kubernetes manifests, Prometheus, Grafana, Discord alerts, and Flux GitOps.",
    "tp-monitoring-prometheus-grafana": "Local Linux monitoring with Docker Compose, Prometheus, Node Exporter, Grafana, and Remote Write.",
    "aks-security-hardening": "AKS security hardening with Entra ID, Azure RBAC, API access restrictions, quotas, and Workload Identity.",
    "azure-aks-infra": "Terraform infrastructure for AKS, ACR, networking, Key Vault integration, persistent storage, and backups.",
    "azure-aks-app": "GitOps deployment of PostgreSQL on AKS with Argo CD, Azure Disk persistence, and Key Vault secrets.",
    "aks-azure-files-nfs": "MongoDB persistence on AKS using private Azure Files NFS storage and dynamic volume provisioning.",
    "azure-buckup-files-lab": "Azure Files SMB lab demonstrating firewall restrictions, soft delete, backup, and file restoration.",
    "aks-velero-azure-backup": "Backup and restore AKS resources with Velero, Azure Blob Storage, Terraform, and Workload Identity.",
    "managed-terraform-state": "Manage an Azure Storage Account with Terraform import, GitLab remote state, versioning, and locking.",
    "kube-microservices-cd": "Helm deployment of Go microservices to AKS through GitLab CI/CD with immutable image tags and OIDC.",
    "kube-microservices-aks": "Go API, books, and movies services with Kind development and GitLab CI image builds for Azure ACR.",
    "kube-microservices-ressources": "Highly available Kubernetes microservices with replicas and pod anti-affinity across simulated zones.",
    "bilan-module-07": "Containerized Go application and MongoDB with Docker Compose, private networking, secrets, and persistent data.",
    "kube-microservices-chaos": "Kubernetes microservices resilience lab with replicas and placement across three simulated availability zones.",
    "kube-microservices": "Deploy Go microservices on Kind with Kubernetes Deployments, Services, replicas, and an API gateway.",
    "kubernetes-nginx": "Kubernetes fundamentals with Nginx on Kind: Deployments, Services, replicas, logs, and self-healing.",
    "compose-go-mongodb-hajar": "Docker Compose training project connecting a Go web application to MongoDB.",
    "simplon-22-pyweb-hajar": "Containerized Flask web app with HTTP access logging and a log viewer endpoint.",
    "tp-github": "GitHub Actions training covering CI/CD workflows, linting, tests, Azure deployment, and repository automation.",
    "azure-infra-cli": "Automate Azure compute, storage, and networking resources with Azure CLI, PowerShell, Bash, and GitHub Actions.",
    "azure-infra-terraform": "Modular Azure infrastructure with Terraform, Blob Storage remote state, and GitHub Actions OIDC deployment.",
    "terraform-azurerm-azure-infra": "Reusable Terraform module for Azure networking, storage, App Service, Functions, and Container Instances.",
    "azure-observability": "Modular Terraform foundation for an Azure application platform and Azure Monitor observability labs.",
    "terraform-azure-observability": "Terraform Azure observability stack with Monitor, Application Insights, Log Analytics, Prometheus, and Grafana.",
    "bilan-azure-frontend": "Angular certification quiz frontend served by Nginx on Azure Web App with automated container delivery.",
    "bilan-azure-backend": "Spring Boot REST API for certification quizzes, questions, sessions, and results, deployed on Azure Web App.",
    "bilan-azure-terraform": "Terraform infrastructure and CI/CD for Azure Quiz, including managed services and an Azure self-hosted runner.",
    "tp-bicep-azure": "Azure compute labs with Bicep: Linux VMs, networking, VM Scale Sets, autoscaling, and App Service slots."
}
KNOWN_GITHUB = {'tp-github', 'azure-infra-cli', 'azure-infra-terraform',
                'terraform-azurerm-azure-infra', 'azure-observability',
                'terraform-azure-observability', 'bilan-azure-frontend',
                'bilan-azure-backend', 'bilan-azure-terraform', 'TP-Bicep-Azure'}


def api(url, payload=None, method=None):
    headers = {'User-Agent': 'Hajar-Simplon-portfolio'}
    if url.startswith('https://api.github.com/'):
        auth_token = os.environ.get('PROFILE_TOKEN', TOKEN) if url.startswith(f'https://api.github.com/repos/{ORG}/.github/contents/') else TOKEN
        headers.update(Authorization='Bearer ' + auth_token,
                       Accept='application/vnd.github+json')
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=60) as response:
        return json.load(response)


def pages(url):
    result = []
    for page in range(1, 1000):
        batch = api(url + ('&' if '?' in url else '?') + f'per_page=100&page={page}')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError('Pagination limit reached')


def category(project):
    topics = project.get('topics') or project.get('tag_list') or []
    text = ' '.join([project['name'], project.get('description') or '', *topics]).lower()
    rules = [('Capstone projects', ('bilan', 'capstone')),
             ('Observability', ('prometheus', 'grafana', 'monitoring', 'observability')),
             ('Reliability and security', ('velero', 'backup', 'buckup', 'chaos', 'security', 'ressources')),
             ('CI/CD and delivery', ('cicd', 'ci/cd', 'gitlab-ci', 'github-actions', '-cd', 'tp-github')),
             ('Infrastructure as code', ('terraform', 'bicep', 'infra', 'managed-state')),
             ('Containers and orchestration', ('kube', 'aks', 'docker', 'compose', 'operator'))]
    for title, words in rules:
        if any(word in text for word in words):
            return title
    return 'Other training projects'


def clean(value):
    return re.sub(r'[\r\n]+', ' ', str(value or '')).replace('|', '\\|').replace('<', '&lt;').replace('>', '&gt;')


def run_git(args, cwd, env):
    # Suppress output: authentication errors must never echo credentials.
    proc = subprocess.run(['git', *args], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if proc.returncode:
        raise RuntimeError('Git operation failed; check token permissions or divergent refs')


def main():
    users = api('https://gitlab.com/api/v4/users?username=' + USER)
    if len(users) != 1 or users[0]['username'] != USER:
        raise RuntimeError('GitLab user could not be identified')
    sources = pages(f"https://gitlab.com/api/v4/users/{users[0]['id']}/projects?visibility=public")
    personal = pages(f'https://api.github.com/users/{USER}/repos?type=owner')
    org_repos = pages(f'https://api.github.com/orgs/{ORG}/repos?type=public')
    existing = {r['name'].lower(): r for r in org_repos}
    projects, errors = [], []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        askpass = root / 'askpass.py'
        askpass.write_text('#!/usr/bin/env python3\nimport os,sys\nprint(os.environ["PORTFOLIO_TOKEN"] if "Password" in sys.argv[1] else "x-access-token")\n')
        askpass.chmod(0o700)
        env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT='0',
                   GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        for p in sources:
            name = p['path'].lower()
            if not re.fullmatch(r'[a-z0-9_.-]+', name) or name == '.github':
                errors.append('Unsupported destination name')
                continue
            source = f'https://gitlab.com/{USER}/{p["path"]}'
            if p.get('web_url') != source:
                errors.append('Unexpected source namespace: ' + name)
                continue
            marker = 'Simplon lab — GitLab source: ' + source
            destination = f'https://github.com/{ORG}/{name}'
            try:
                if name not in existing:
                    existing[name] = api(f'https://api.github.com/orgs/{ORG}/repos',
                                         {'name': name, 'description': marker, 'private': False,
                                          'auto_init': False})
                if not existing[name].get('description') or existing[name].get('description') not in (marker, marker.replace('GitLab source:', 'GitLab mirror source:'), DESCRIPTIONS.get(name)):
                    raise RuntimeError('Destination name collision; repository left untouched')
                if p.get('default_branch'):
                    checkout = root / name
                    run_git(['clone', '--bare', source + '.git', str(checkout)], root, env)
                    run_git(['push', destination + '.git', 'refs/heads/*:refs/heads/*',
                             'refs/tags/*:refs/tags/*'], checkout, env)
                projects.append(dict(p, portfolio_url=destination, source_url=source))
                print('Synchronized ' + name)
            except Exception as exc:
                errors.append(name + ': ' + str(exc))
                projects.append(dict(p, portfolio_url=source, source_url=source))
        mirrored_names = {p['path'].lower() for p in sources}
        for p in personal:
            if not p.get('private') and (p['name'] in KNOWN_GITHUB or 'simplon' in p.get('topics', [])):
                projects.append(dict(p, portfolio_url=p['html_url'], source_url=p['html_url']))
        for p in org_repos:
            if p['name'] != '.github' and p['name'].lower() not in mirrored_names:
                projects.append(dict(p, portfolio_url=p['html_url'], source_url=p['html_url']))
    sections = {}
    for p in projects:
        p['description'] = DESCRIPTIONS.get(p['name'].lower(), p.get('description') or '')
        sections.setdefault(category(p), []).append(p)
    text = '# Hajar at Simplon\n\nCloud & DevOps training portfolio.\n\n'
    text += '## Skills and project areas\n\nAzure · AKS · Terraform · Bicep · Docker · Kubernetes · CI/CD · Prometheus · Grafana · Velero\n\n'
    text += 'GitLab projects are copied to GitHub automatically. Develop in the source repository.\n\n'
    text += 'Projects are grouped using repository names, descriptions, and topics.\n\n'
    for title, items in sorted(sections.items()):
        text += f'## {title}\n\n| Project | Description | Source |\n| --- | --- | --- |\n'
        for p in sorted(items, key=lambda p: p['name'].lower()):
            text += f'| [{clean(p["name"])}]({p["portfolio_url"]}) | {clean(p.get("description"))} | [Source]({p["source_url"]}) |\n'
        text += '\n'
    text += '---\nAutomatically refreshed every six hours. New personal GitHub projects are included when tagged `simplon`. Only public projects are included.\n'
    url = f'https://api.github.com/repos/{ORG}/.github/contents/profile/README.md'
    old = api(url)
    if base64.b64decode(old['content']).decode() != text:
        api(url, {'message': 'Refresh Simplon project inventory', 'sha': old['sha'],
                  'content': base64.b64encode(text.encode()).decode()}, method='PUT')
    if errors:
        raise RuntimeError('; '.join(errors))


if __name__ == '__main__':
    main()
