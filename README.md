# SongStructurer

[![CI](https://github.com/edsoftitaly/SongStructurer/actions/workflows/ci.yml/badge.svg)](https://github.com/edsoftitaly/SongStructurer/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

**SongStructurer** analizza un file audio e ne ricostruisce la struttura: trova i punti in cui il
brano cambia sezione, riconosce le sezioni che si ripetono e propone un nome per ognuna
(Intro, Verse, Chorus, Bridge...). Il risultato si corregge su una timeline interattiva e si
esporta in CSV, JSON, etichette Audacity o PNG.

Tutto gira in locale: nessun upload, nessuna connessione, nessun modello da scaricare.

## Caratteristiche

- **Analisi strutturale**: confini di sezione, gruppi di sezioni ripetute, etichette funzionali,
  BPM e tonalità stimati
- **Timeline modificabile**: trascina i confini, dividi, unisci, rinomina, annulla/ripeti
- **Riproduzione**: brano intero o singola sezione, seek con un clic sulla forma d'onda
- **Esportazione**: CSV (millisecondi), JSON, etichette Audacity, PNG
- **Riga di comando**: `songstructurer analyze brano.mp3 -o brano.json`

## Installazione

Scarica `SongStructurer.exe` dalla [pagina delle release](https://github.com/edsoftitaly/SongStructurer/releases)
ed eseguilo: è portable, non richiede installazione. Nella release trovi anche `SHA256SUMS.txt`
per verificare il download:

```powershell
Get-FileHash SongStructurer.exe -Algorithm SHA256
```

Requisiti: Windows 10/11 a 64 bit. Formati letti: MP3, WAV, FLAC, OGG, AIFF.

### Da sorgente

```bash
pip install .
songstructurer
```

## Come funziona l'analisi

1. beat tracking, poi feature timbriche (MFCC) e armoniche (chroma) per ogni beat;
2. due matrici di auto-similarità, una per famiglia di feature;
3. curva di novelty con kernel a scacchiera lungo la diagonale: i picchi sono i confini;
4. confronto tra sezioni e clustering: le sezioni simili finiscono nello stesso gruppo;
5. i gruppi ricevono un nome in base a ripetizioni, energia e posizione nel brano.

I punti 1-4 misurano l'audio. Il punto 5 è un'euristica: **i nomi sono una proposta da
verificare a orecchio**, soprattutto su brani che non seguono la forma strofa/ritornello.

### Accuratezza misurata

Su quattro brani metal con annotazioni di riferimento (dataset Sargon di
[msaf-data](https://github.com/urinieto/msaf-data)), con le metriche standard di `mir_eval`:

| | v1.0 | v2.0 |
|---|---|---|
| Confini entro 0,5 s (F) | 0,09 | 0,41 |
| Confini entro 3 s (F) | 0,49 | 0,66 |
| Sezioni ripetute (pairwise F) | 0,29 | 0,70 |

Quattro brani sono un campione piccolo: i numeri indicano l'ordine di grandezza, non una
garanzia. I servizi online basati su reti neurali addestrate su migliaia di brani annotati
restano più precisi, in particolare nel dare il nome giusto alle sezioni.
Per ripetere la misura: `python tools/benchmark.py CARTELLA_AUDIO CARTELLA_JAMS`.

## Sviluppo

```bash
pip install -e ".[dev,build]"
ruff check . && ruff format --check .
pytest
pyinstaller --noconfirm --clean packaging/SongStructurer.spec
```

### Pubblicare una release

1. aggiorna `__version__` in `src/songstructurer/__init__.py` e `CHANGELOG.md`;
2. crea e pubblica il tag: `git tag v2.0.1 && git push origin v2.0.1`.

GitHub Actions esegue i test, costruisce l'eseguibile Windows, lo collauda (`--selftest`),
calcola lo SHA-256 e pubblica la release con le note prese dal changelog.

## Licenza

GPL-3.0. Vedi [LICENSE](LICENSE).
