# Running your own instance

Ubuntu 24.04; use 4 vCPU and 8-16 GB RAM for the live simulator, with several GB
of disk for source data preparation. No GPU. Unlike the cached recording, live
mode runs the full neural simulation on this server for each visitor. It calls
production Neuroadapt for inspection-budget learning, not tile selection.

Set your own hostname in both configuration files. Keep `PUBLIC_ORIGIN` exactly aligned with the browser's HTTPS origin.

1. Install packages and create the unprivileged service user:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv g++ git caddy rsync
sudo useradd --system --home /opt/fly-captcha --shell /usr/sbin/nologin flydemo
```

2. Place this repository at `/opt/fly-captcha` using your authenticated deployment account. Do not copy `.git`, private keys, local experiment outputs, credentials or a developer's environment. Keep application files owned by the deployment account/root, readable but not writable by `flydemo`.

```bash
cd /opt/fly-captcha
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt -r requirements-sensory.txt
sudo .venv/bin/python setup_fly.py
sudo install -m 644 deploy/fly-captcha.service /etc/systemd/system/fly-captcha.service
sudo install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now fly-captcha
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The Caddy installation step assumes no existing sites. If other sites exist, merge the site block; do not replace other applications' configuration.

3. Permit inbound TCP 22, 80 and 443 in your provider firewall. The Python service binds only to loopback. Caddy obtains and renews the hostname's HTTPS certificate. Do not send API keys to a plain HTTP page or disable certificate validation.

4. Verify:

```bash
curl --fail https://YOUR_HOSTNAME/healthz
sudo systemctl status fly-captcha --no-pager
```

Watch `/` without a key, then open `/live` and supply your own key. Verify
training advances and results report admitted controller feedback, zero test
feedback and unchanged public policy state during evaluation. Play a practice
board, stop one, then request another. Verify a second browser cannot read or
stop the first browser's session.

The service uses two active CPU slots and three retained sessions. Each retained
fly keeps its simulator and readouts in memory for practice. It has an 8 GB
systemd memory limit and one numerical compute thread per run. Do not increase
capacity before measuring resident and peak memory on the target machine.

If you already prepared the pinned graph elsewhere, transfer only the verified
upstream `doom/` sources, `outputs/doom/malecns_v1/graph.npz`,
`connectome_data/malecns_v1/annotations.feather` and
`connectome_data/malecns_v1/normalized/neurons.feather` into `vendor/doomfly`.
Compile the original native source on the destination CPU with
`.venv/bin/python deploy/compile_runtime.py vendor/doomfly`. Do not copy a
machine-specific binary or a task-trained checkpoint. Full preparation with
`setup_fly.py` remains the standard reproducible route.

## Updates and privacy

Wait for active runs before restarting. Keys stay only in RAM; traces are
temporary files in `/run/fly-captcha`, a private runtime directory removed on
service stop. Sessions and downloads expire after two hours. Forget session
closes the upstream client, drops the key/learner and removes its artifacts.
Hosted Domains persist in the creating account. No server API key is configured.

For upgrades, stage and test a separate release directory first. Keep the old
release and service configuration outside the repository as rollback material.
Switch the unit's `WorkingDirectory` and executable path together, then restart.
If startup or health checks fail, restore the previous unit and restart it. The
site's Caddy origin and loopback upstream port can remain unchanged.

Run a **single worker**: visitor-run state is process-local. Raising Uvicorn worker count without adding a shared, securely designed job/session store breaks ownership and polling. Start with the shipped concurrency limits and measure resource use before increasing them.

Keep access/body logging disabled in application and reverse proxy. Do not enable request capture, verbose HTTP diagnostics, crash dumps or swap as a way to debug visitor-key requests. Use dedicated API keys and revoke them if exposed. The server operator necessarily has access to process memory; use only trusted hosts.
