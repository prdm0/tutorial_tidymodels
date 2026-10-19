# curso_ml

Curso de Machine Learning

## Mídias locais e publicação

A apresentação não depende de serviços externos em tempo de execução: mapa,
vídeo, capturas das páginas de documentação/aplicações, KaTeX, Fira Code e a
textura do `.flow` ficam em `apresentacao/media/`, travados por SHA-256 em
`apresentacao/media/manifest.json` (com origem e licença de cada arquivo).

Ambiente (uma vez, a partir da raiz do repositório):

```sh
python3 -m venv apresentacao/.media-build/venv
apresentacao/.media-build/venv/bin/python -m pip install -r scripts/requirements-media.txt
apresentacao/.media-build/venv/bin/python -m playwright install chromium webkit
export PATH="$PWD/apresentacao/.media-build/venv/bin:$PATH"
```

| Comando | Para quê |
|---|---|
| `python3 scripts/media.py prepare` | Adquire e trava as mídias originais (exige rede na primeira vez) |
| `python3 scripts/media.py prepare --refresh-lock` | Atualiza deliberadamente origens/capturas e os hashes travados |
| `python3 scripts/media.py repair` | Restaura mídia ausente/corrompida a partir do lock, sem sobrescrever edições válidas |
| `python3 scripts/build_deck.py` | Repara mídias, renderiza em staging, audita, gera `media-build.json` e promove `apresentacao/docs/` e `docs/` |
| `python3 scripts/check_media.py --root docs --source apresentacao --report r.json --require-receipt` | Audita um site já publicado (grafo HTML/CSS/SVG, decodificação real, Chromium e WebKit, http e `file://` offline) |
| `python3 -m unittest discover -s tests -p 'test_media.py'` | Testes do pipeline de mídias |

`build_deck.py` nunca publica build parcial: a troca dos dois diretórios é
atômica e, se algo falhar, a versão anterior é restaurada. O workflow
`.github/workflows/pages.yml` repete a auditoria no CI e só envia o artefato
do GitHub Pages depois que ela passa.
