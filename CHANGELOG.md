# Changelog

## [2.0.0] - 2026-11-20

Riscrittura completa.

### Analisi
- Nuovo motore di analisi strutturale: feature timbriche e armoniche sincronizzate
  ai beat, matrici di auto-similarità, curva di novelty con kernel a scacchiera,
  raggruppamento delle sezioni che si ripetono. La versione 1 tagliava il brano
  ogni 8 secondi circa sulla griglia dei beat, senza guardare la struttura.
- Etichette funzionali proposte in automatico (Intro, Verse, Pre-Chorus, Chorus,
  Bridge, Break, Outro...): sono un'euristica da verificare a orecchio.
- Stima di BPM e tonalità, riconoscimento del silenzio iniziale e finale.
- Le sezioni coprono tutto il brano, da 0 alla fine, senza buchi.

### Applicazione
- Caricamento e analisi in background: la finestra non si blocca più.
- Riproduzione dalla memoria con seek reale, play/pausa dell'intero brano e
  ascolto della singola sezione (prima: file WAV temporanei e seek non funzionante).
- Forma d'onda disegnata con minimi e massimi (prima la media azzerava il segnale),
  colori per etichetta, cursore di riproduzione fluido.
- Confini condivisi tra sezioni adiacenti, trascinabili a qualsiasi zoom;
  dividi, unisci, rinomina (anche tutte le sezioni uguali), annulla/ripeti.
- Zoom con rotella, clic per posizionare il cursore, menu contestuale.
- Finestra ridimensionabile.

### Esportazione
- CSV con tempi al millisecondo (prima troncati al secondo), JSON,
  etichette Audacity, PNG dell'intero brano.

### Progetto
- Pacchetto Python installabile, riga di comando (`songstructurer analyze`),
  test automatici, lint.
- Build e release automatiche con GitHub Actions: l'eseguibile Windows viene
  costruito, collaudato e pubblicato quando su `main` arriva una nuova versione.
- Rimossi dal file .spec il percorso assoluto di una cartella personale e UPX.

## [1.0] - 2025-09-29

Prima versione.
