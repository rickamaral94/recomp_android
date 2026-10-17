# Diagnóstico exportável

## Como exportar (aparelho)

1. Abra o app. A tela mostra o `report.json` da sessão atual.
2. Toque em **Exportar diagnóstico (ZIP)** e escolha onde salvar (Storage Access Framework; sem
   root e sem permissão de armazenamento).
3. Para validar no PC: `python3 tools/check_report.py recomp_android-diag-*.zip`.

## Conteúdo do ZIP

| Entrada | Origem |
|---|---|
| `report.json` | gerado pelo código nativo (`common/src/report.cpp`) |
| `logs/session.log` | log da sessão (`recomp::log`), em `<externalFilesDir>/logs/` |
| `logs/logcat.txt` | `logcat -d --pid=<pid do app>`: só as linhas do próprio processo |

Logs maiores que 4 MiB são cortados no começo (o fim é preservado, com um marcador). O ZIP nunca
inclui arquivos de jogo, BIOS, firmware ou chaves.

## `report.json` — esquema versão 1

`schema = "recomp_android.diagnostic-report"`, `schema_version = 1`.

| Chave | Conteúdo |
|---|---|
| `generated_at` | ISO-8601 UTC |
| `build` | `commit`, `dirty`, `version`, `build_type`, `abi`, `compiler`, `ndk` |
| `device` | `manufacturer`, `model`, `device`, `os`, `os_release`, `sdk_int`, `soc_manufacturer`, `soc_model`, `hardware`, `supported_abis` |
| `vulkan` | `loader_found`, `instance_created`, `instance_api_version`, `error`, `devices[]` com `name`, `vendor_id`, `device_id`, `type`, `api_version`, `driver_version_raw`, `driver_version` (decodificado conforme o fabricante), `driver_id`, `driver_name`, `driver_info`, `extensions[]` (ordenadas) |
| `game` | `null` até a Fase 2 (ID, região, versão, hashes dos arquivos locais) |
| `analysis` | `tools[]` e `findings[]` (ferramenta/versão, endereço, função, evidência, confiança) — vazios no M0 |
| `recompilation` | `null` até o M1 (cobertura, funções pendentes, stubs acionados, exceções) |
| `metrics` | cada métrica é `{"collected": false, "reason": …}` até ser medida de verdade |
| `tests[]` | `name`, `status` (`passed`/`failed`/`skipped`), `detail` |
| `result` | `level` na escala `none, compiled, installed, opened, profile_loaded, reached_menu, reached_gameplay, stability_passed` e `note` |
| `limitations[]` | texto livre |

Regra: o que não foi medido aparece como não coletado (`null` ou `collected: false` com motivo),
nunca como zero ou estimativa.

### Exemplo real (host, lavapipe)

Saída de `recomp-report` neste ambiente (trecho):

```json
"vulkan": {"loader_found": true, "instance_created": true, "instance_api_version": "1.4.318",
  "devices": [{"name": "llvmpipe (LLVM 20.1.2, 256 bits)", "vendor_id": "0x00010005",
    "type": "cpu", "api_version": "1.4.318", "driver_version_raw": "0x06402008",
    "driver_version": "25.2.8", "driver_id": 13, "driver_name": "llvmpipe",
    "driver_info": "Mesa 25.2.8-0ubuntu0.24.04.4 (LLVM 20.1.2)", "extensions": ["…161 itens…"]}]}
```

Ainda não há saída de um Adreno 740: depende de rodar o APK no Odin 2 Portal.
