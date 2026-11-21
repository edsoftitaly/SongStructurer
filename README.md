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
- **Traccia guida**: il brano con i beep sui beat e la raffica di clic che annuncia ogni
  cambio di sezione, in MP3, WAV o FLAC
- **Accordi**: triadi maggiori, minori e quinte stimate sui beat, in una corsia sotto la forma
  d'onda
- **Stem e MIDI** (con Demucs): voce, basso, batteria, altro, più chitarra e piano con il
  modello a 6 stem; melodia e basso trascritti in un file MIDI a due tracce
- **Esportazione**: CSV (millisecondi), JSON, etichette Audacity, PNG
- **Motore neurale opzionale**: lo stesso modello All-In-One usato da vari analizzatori online
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

## Motore neurale (opzionale)

Il motore integrato è DSP classico. Per etichette più affidabili e per i downbeat si può usare
[All-In-One](https://github.com/mir-aidj/all-in-one) (`allin1`), che richiede PyTorch e Demucs:
diversi gigabyte, quindi non sta nell'eseguibile. SongStructurer lo avvia in un interprete Python
esterno:

1. in un ambiente Python a parte installa `allin1` seguendo le istruzioni del progetto
   (con una build CUDA di torch l'analisi dura secondi invece di minuti);
2. in SongStructurer: **Analisi → Configura Python per il motore neurale…** e scegli il
   `python.exe` di quell'ambiente. L'app verifica che `allin1` e `torch` si importino;
3. da quel momento **Analizza** usa il motore neurale. Dal menu Analisi si torna al classico.

In alternativa: variabile d'ambiente `SONGSTRUCTURER_PYTHON`, oppure da riga di comando
`songstructurer analyze brano.mp3 --engine neural --python C:\percorso\python.exe`.

Lo stesso interprete serve a **File → Esporta → Stem separati** e **MIDI di melodia e basso**:
Demucs viene installato insieme ad `allin1`. Il MIDI nasce dagli stem di voce e basso, una nota
alla volta: armonie vocali e accordi di basso non vengono trascritti.

Al primo uso `allin1` e Demucs scaricano i pesi dei modelli: serve la connessione.

Stato: l'integrazione è collaudata con moduli `allin1` e `demucs` simulati (avvio
dell'interprete, scambio dei dati, errori). **Non è stata ancora provata con i modelli reali.**
Accordi e trascrizione sono collaudati su segnali sintetici, non su un set di brani annotati.

## Sviluppo

```bash
pip install -e ".[dev,build]"
ruff check . && ruff format --check .
pytest
pyinstaller --noconfirm --clean packaging/SongStructurer.spec
```

### Pubblicare una release

1. aggiorna `__version__` in `src/songstructurer/__init__.py` e `CHANGELOG.md`;
2. porta la modifica su `main` (merge della pull request).

Quando su `main` arriva un numero di versione che non ha ancora un tag, la release parte da
sola. In alternativa si può pubblicare un tag `vX.Y.Z` a mano: deve coincidere con `__version__`.

GitHub Actions esegue i test, costruisce l'eseguibile Windows, lo collauda (`--selftest`),
calcola lo SHA-256 e pubblica la release con le note prese dal changelog.

## Licenza

GPL-3.0. Vedi [LICENSE](LICENSE).
