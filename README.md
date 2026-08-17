# claude-session-refresh

Apre una finestra di utilizzo di Claude Code a **orari fissi e prevedibili**: 08:00, 13:00,
18:00 e 23:00 (ora italiana).

## Il problema

Le finestre di utilizzo di Claude Code durano 5 ore e partono al primo messaggio. Il confine
cade quindi a caso, a seconda di quando si comincia a lavorare, e non si sa mai davvero quando
la quota si rinnova.

Questo progetto non compra quota: compra **prevedibilità**. Un trigger automatico apre una
finestra sempre alla stessa ora, così le finestre diventano `8–13`, `13–18`, `18–23`, `23–04`.

Il valore dell'idea sta tutto nel sapere l'orario in anticipo, quindi **la puntualità è il
requisito, non un dettaglio**.

Il buco fra le **04:00 e le 08:00 è voluto**: quattro finestre coprono venti ore su ventiquattro
e la notte non c'è bisogno di ancorarla.

## Come funziona

Un workflow GitHub Actions (`.github/workflows/refresh.yml`) esegue davvero la CLI `claude` —
non una POST HTTP — autenticandosi con il token di `claude setup-token`.

### Perché così, e non altrimenti

- **Gira in cloud, non sul Mac.** Un LaunchAgent locale non è un trigger: se il Mac è spento non
  parte. Il runner è GitHub Actions.
- **Esegue la CLI, non l'API.** Il token OAuth (`sk-ant-oat01-…`) autentica l'abbonamento, ed è
  quello che serve: una normale API key spenderebbe crediti API e **non toccherebbe la finestra
  da 5 ore**. Quel token però è accettato solo da Claude Code, non dalla Messages API — il che
  esclude Cloudflare Workers e qualunque runtime serverless senza subprocess.
- **La repo è pubblica.** Il job dorme (vedi sotto) e una dormita consuma minuti Actions; sulle
  repo private i minuti sono a quota (500/mese sul Free, 3000 sul Pro) e quattro run al giorno
  con dormite fino a mezz'ora fanno ~1900–3700 minuti al mese, cioè si sfora. Sulle repo
  pubbliche i minuti sono illimitati e gratis. Nel codice non c'è niente di sensibile: il token
  vive nei GitHub secrets, e i secrets non vengono passati ai workflow delle fork.

### Il design centrale: anticipare **e** dormire

Il cron di GitHub Actions non è puntuale: ritardi di 15+ minuti sono normali (peggiorati da
febbraio 2026) e sotto carico un run può essere saltato del tutto.

Anticipare il cron da solo non risolve niente: se il job parte alle 7:30, la finestra si apre
alle 7:30, l'ancora si sposta e l'incertezza resta identica. La soluzione è anticipare **e far
aspettare il job**:

1. il cron è schedulato **30 minuti prima** del target (7:30 / 12:30 / 17:30 / 22:30 locali);
2. il job calcola il target successivo e **dorme fino allo scoccare dell'ora esatta**;
3. solo allora manda il ping.

Finché il ritardo di GitHub sta sotto i 30 minuti — quasi sempre — la finestra si apre alle
**8:00:0x precise**: il ritardo viene assorbito dal buffer invece di propagarsi sull'orario.

Per lo stesso motivo `npm i -g @anthropic-ai/claude-code` gira **prima** della dormita: al
risveglio il ping parte subito, senza venti secondi di installazione a spostare l'orario.

### Gli step

| # | Step | Cosa fa |
|---|------|---------|
| 1 | Calcola il target | Guard di stagione + cerca il primo orario fra 08/13/18/23 che cada da −60 a +45 minuti rispetto ad adesso. Se non ce n'è, il run esce pulito. |
| 2 | Installa Claude Code | `npm i -g @anthropic-ai/claude-code`, prima della dormita. |
| 3 | Attendi lo scoccare dell'ora | `sleep` fino al secondo esatto del target. Se il target è già passato, procede subito e registra il ritardo. |
| 4 | Ping | `claude -p --model haiku --safe-mode --no-session-persistence "Rispondi solo: ok"`. `--safe-mode` evita hook/MCP/plugin, `--model haiku` tiene il costo a briciole. |
| 5 | Log + commit | Appende una riga a `log/YYYY-MM.md` e committa. |

### Il doppio cron e il guard di stagione

Il cron di Actions è **solo UTC e non conosce l'ora legale**, quindi servono due serie di voci:

```yaml
on:
  schedule:
    - cron: '30 6,11,16,21 * * *'   # inverno CET  (UTC+1) -> 7:30/12:30/17:30/22:30 locali
    - cron: '30 5,10,15,20 * * *'   # estate  CEST (UTC+2) -> idem
  workflow_dispatch:
```

Metà delle voci, a seconda della stagione, non deve fare niente. Non basta però la finestra
temporale a scartarle: in estate il cron invernale parte alle 8:30 locali, e il target delle
8:00 gli risulta a −30 minuti, cioè dentro la tolleranza per i ritardi. Sembrerebbe un cron in
ritardo, e pingherebbe.

Il workflow confronta quindi `github.event.schedule` (la voce di cron che ha triggerato il run)
con l'offset UTC attuale di `Europe/Rome`, e se non corrispondono esce subito. I run manuali
(`workflow_dispatch`) saltano il controllo.

### Il log

Ogni run riuscito appende una riga a `log/YYYY-MM.md`:

```
2026-08-17 08:00 — finestra aperta (cron in ritardo di 4 min) → scade 13:00
```

Serve a due cose insieme:

- è **lo storico leggibile delle finestre**, e dice anche quanto ritarda davvero il cron;
- **tiene viva la repo**: le repo pubbliche si vedono disattivare i workflow schedulati dopo 60
  giorni di inattività, e un commit al giorno spegne il problema.

I commit fatti col `GITHUB_TOKEN` non ri-triggerano workflow, quindi non c'è nessun loop.
Orario e scadenza finiscono anche nel summary del run.

## Setup una tantum

Il token non passa dall'agente: si genera e si carica a mano.

```bash
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo limonequantistico/claude-session-refresh
```

### Rigenerare il token

I token OAuth scadono. Quando il ping comincia a fallire in autenticazione, si rifà la stessa
coppia di comandi: `claude setup-token` genera un token nuovo e `gh secret set` lo sovrascrive.
Nient'altro da cambiare — il workflow legge sempre `secrets.CLAUDE_CODE_OAUTH_TOKEN`.

## Verifica — in quest'ordine

1. **Run manuale.**

   ```bash
   gh workflow run refresh.yml
   ```

   Deve finire verde, il summary deve mostrare il ping ok e deve comparire il commit di log. Se
   fallisce sull'auth, il problema è il token o il nome della variabile d'ambiente.

   Nota: GitHub impiega fino a un'ora a registrare uno schedule nuovo, quindi **il primo run va
   fatto per forza a mano**. E ricorda che il run manuale fa qualcosa solo se lanciato entro la
   finestra −60/+45 minuti da uno dei quattro orari; fuori da lì esce pulito senza pingare.

2. **La prova che conta.** Subito dopo un run riuscito, aprire Claude Code in locale e lanciare
   `/usage`. L'orario di reset deve essere **~5 ore dopo l'orario del run**. Se `/usage` mostra
   un reset che non c'entra, il ping non ha aperto la finestra e l'intera idea non regge.

3. **Un paio di giorni di rodaggio.** Leggere `log/`: dice sia gli orari reali sia quanto ritarda
   davvero il cron, cioè se il buffer da 30 minuti è tarato bene.

## Come cambiare gli orari

Gli orari stanno in due posti e vanno tenuti allineati:

1. `TARGET_HOURS` nell'`env` del job — le ore locali dei target (`8 13 18 23`);
2. le due voci di `cron`, che devono valere **30 minuti prima** di ogni target, una serie per
   `UTC+1` e una per `UTC+2`;
3. se cambiano le voci di cron, vanno aggiornate anche le stringhe nel guard di stagione
   (`attesa=`), che le confronta letteralmente.

Ricorda che le finestre durano 5 ore: target più fitti di così si sovrappongono e i ping in
eccesso non fanno niente.

## Come allargare il buffer

Il buffer sono due variabili nell'`env` del job:

- `EARLY_S` (default `2700`, 45 min) — quanto lontano nel futuro può stare un target perché il
  job lo aspetti dormendo;
- `LATE_S` (default `3600`, 60 min) — quanto indietro nel passato può stare un target perché il
  job lo pinghi comunque, in ritardo.

Per allargare la protezione contro i ritardi bisogna anticipare il cron (es. 45 o 60 minuti
prima invece di 30) e alzare `EARLY_S` di conseguenza. Costa solo minuti Actions, che su repo
pubblica sono gratis. Attenzione a non alzare troppo `LATE_S` oltre l'anticipo del cron: più si
allarga, più diventa possibile che il guard di stagione debba fare tutto il lavoro da solo.

## Rischi noti

- **Ritardi oltre i 30 minuti.** Rari ma esistono. Il buffer li assorbe fino a mezz'ora; oltre,
  la finestra si apre in ritardo e il log lo dice. Se GitHub salta del tutto un run schedulato,
  quella finestra non viene ancorata.
- **Se uso Claude prima delle 8**, parte lì una finestra e quella delle 8:00 ci ricade dentro
  senza fare niente; il sistema si riallinea alle 13. È una proprietà, non un bug: il trigger
  apre una finestra solo se non ce n'è già una aperta.
- **Il token scade** e va rigenerato a mano (vedi sopra).

## Fuori scope in v1

Notifiche push (ntfy/Telegram). Col Mac spento la notifica macOS non ha senso, e il valore è già
nel sapere gli orari in anticipo.
