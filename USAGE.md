# Guida all'uso

## Aprire e analizzare

1. **Apri…** (Ctrl+O) e scegli un file audio. Puoi anche passare il file come argomento
   all'eseguibile.
2. L'analisi parte da sola al termine del caricamento. La barra in basso mostra l'avanzamento,
   la finestra resta utilizzabile.
3. Al termine la forma d'onda è divisa in sezioni colorate: stesso colore, stessa etichetta.
   In basso a destra trovi BPM e tonalità stimati.

**Analizza** ripete l'analisi e sostituisce le sezioni; si annulla con Ctrl+Z.

I nomi delle sezioni sono una proposta. I confini e i gruppi di sezioni ripetute vengono
dall'audio, i nomi da un'euristica: controllali ascoltando.

## Ascoltare

| Azione | Come |
|---|---|
| Play / pausa dal cursore | pulsante **Play** o barra spaziatrice |
| Spostare il cursore | clic sulla forma d'onda |
| Ascoltare una sezione | selezionala e premi **Sezione** |
| Fermare e rilasciare la scheda audio | **Stop** |

## Correggere la struttura

| Azione | Come |
|---|---|
| Spostare un confine | trascina la linea verticale tra due sezioni |
| Dividere una sezione | cursore nel punto giusto, poi **Dividi** (tasto S), oppure clic destro → *Dividi qui* |
| Unire sezioni | selezionane due o più adiacenti nella tabella (Maiusc+clic), poi **Unisci** (tasto M) |
| Eliminare un confine | clic destro sulla sezione → *Elimina confine a sinistra* |
| Rinominare | doppio clic sulla sezione, **Rinomina** o F2 |
| Rinominare tutte le sezioni uguali | nella finestra di rinomina spunta *Applica a tutte le sezioni uguali* |
| Annullare / ripetere | Ctrl+Z / Ctrl+Y |

Le sezioni coprono sempre tutto il brano: spostando un confine si accorcia una sezione e si
allunga la vicina. La durata minima di una sezione è 0,25 secondi.

## Zoom

- rotella del mouse sulla forma d'onda: zoom attorno al puntatore
- pulsanti **−** e **+**, **Tutto** per rivedere il brano intero
- barra di scorrimento sotto la forma d'onda

Durante la riproduzione la vista segue il cursore.

## Esportare

Menu **File → Esporta**:

- **CSV**: `index, start_s, end_s, duration_s, start, end, label`, tempi al millisecondo
- **JSON**: sezioni più nome del file, BPM e tonalità
- **Etichette Audacity (TXT)**: `inizio<TAB>fine<TAB>etichetta`, tempi in secondi
- **PNG**: l'intero brano con sezioni ed etichette
- **Traccia guida con beep**: il brano originale più un clic su ogni beat (più acuto sul primo
  movimento della battuta, solo con il motore neurale). Nei 4 secondi prima di ogni cambio di
  sezione parte una raffica di 25 clic sempre più ravvicinati e sempre più acuti, e sul cambio
  uno sweep discendente. Usa i confini come li vedi nella timeline, correzioni comprese.

- **Accordi (TXT Audacity)**: la sequenza di accordi come traccia di etichette
- **MIDI di melodia e basso**: due tracce, trascritte dagli stem di voce e basso. Se gli stem
  non sono ancora stati separati in questa sessione, parte prima Demucs
- **Stem separati (Demucs)**: un WAV per stem nella cartella scelta, 4 o 6 stem

Stem e MIDI richiedono il Python esterno del motore neurale (vedi README).

## Accordi

Sotto la forma d'onda scorre la corsia degli accordi: i nomi compaiono quando lo zoom lascia
abbastanza spazio. Il riconoscimento distingue triadi maggiori (`C`), minori (`Cm`) e quinte
(`C5`); non riconosce settime, rivolti o accordi alterati. È una stima: sul materiale molto
distorto o con accordature ribassate va presa con cautela.

## Riga di comando

```bash
songstructurer analyze brano.mp3                # JSON su standard output
songstructurer analyze brano.mp3 -o brano.csv   # il formato dipende dall'estensione
songstructurer click brano.mp3 -o brano.click.mp3   # traccia guida con i beep
songstructurer analyze brano.mp3 --engine neural   # motore neurale (vedi README)
songstructurer stems brano.mp3 -o cartella --model htdemucs_6s   # stem con Demucs
songstructurer midi brano.mp3 -o brano.mid         # melodia e basso in MIDI
songstructurer --selftest                       # verifica che il motore di analisi funzioni
```

## Problemi comuni

**La riproduzione non parte.** Il messaggio di errore riporta la risposta della scheda audio.
Controlla che ci sia un dispositivo di uscita predefinito in Windows.

**Un file non si apre.** Il messaggio riporta l'errore del decoder. Prova a convertirlo in WAV
o FLAC.

**Troppe o troppe poche sezioni.** L'analisi lavora meglio su brani con sezioni ben distinte
per arrangiamento o armonia. Unisci o dividi a mano dove serve.
