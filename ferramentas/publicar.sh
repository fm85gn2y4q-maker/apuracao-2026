#!/bin/bash
# Copia o estado dos monitores para dados/ e publica no GitHub Pages a cada N segundos.
cd "$(dirname "$0")/.."
while true; do
  for f in painel-estado.json painel-historico.json monitor-estado.json; do
    [ -f "ferramentas/$f" ] && cp "ferramentas/$f" "dados/$f"
  done
  git add dados >/dev/null 2>&1
  if ! git diff --cached --quiet; then
    git -c user.name="Matheus Menegatti" -c user.email="matheusmenegatti.adv@gmail.com" commit -q -m "Dados da apuração $(date +%H:%M)" && git push -q 2>/dev/null && echo "[$(date +%H:%M:%S)] publicado"
  fi
  sleep ${1:-90}
done
