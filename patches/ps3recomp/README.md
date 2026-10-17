# Patches sobre o ps3recomp

O submódulo `third_party/ps3recomp` continua apontando para o upstream sem alterações
(`39a36296`). Os patches daqui são aplicados a uma **cópia** das ferramentas, dentro do
diretório de build, por `tests/ps3/ppu_diff/run_diff.py`. O relatório (`report.json`)
registra quais foram aplicados.

| Patch | O que corrige | Como foi achado |
|---|---|---|
| `0001-jump-table-window-stops-at-block-end.patch` | A detecção de tabelas de salto olhava 30 instruções para trás sem respeitar o fim do bloco ou da função anterior. Um `switch` com tabela absoluta, logo depois de outro com tabela relativa, era decodificado como relativo, e o `bctr` virava chamada indireta sem destino | suíte `flow` do teste diferencial |

Cada patch deve ir também para o upstream. Ainda não foi enviado: depende da sua autorização,
porque é uma ação num repositório de terceiros.

Licença: o projeto é GPL-3.0-or-later e o ps3recomp é MIT. Para entrar no upstream, o patch
precisa ser oferecido sob MIT. Essa decisão é sua e entra junto com a autorização de envio.
