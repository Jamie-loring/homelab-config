FROM node:22-slim

RUN apt-get update && apt-get install -y \
    openssh-server tmux git curl wget \
    python3 python3-mutagen \
    docker.io \
    && npm install -g @anthropic-ai/claude-code \
    && mkdir -p /var/run/sshd /root/.ssh \
    && chmod 700 /root/.ssh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# SSH: key-only, root allowed, port 2222
RUN sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config \
    && sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config \
    && echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

COPY authorized_keys /root/.ssh/authorized_keys
RUN chmod 600 /root/.ssh/authorized_keys

COPY CLAUDE.md /root/CLAUDE.md

# Auto-attach to tmux on SSH login
RUN printf '\n# Auto-attach to tmux on SSH\nif [ -z "$TMUX" ] && [ -n "$SSH_CONNECTION" ]; then\n    tmux attach-session -t main 2>/dev/null || tmux new-session -s main\nfi\n' >> /root/.bashrc

EXPOSE 2222

CMD ["/usr/sbin/sshd", "-D"]
