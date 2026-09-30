# Security- en privacycontrole

Datum: 2026-09-30. Scope: aanwezige Python-broncode, Jev-integratie, GUI/webapp-templates, scripts en buildconfiguratie. Handmatige broncodecontrole en lokale reproducties; geen live gameplay, netwerkcapture, dependency-audit of onderzoek naar gegevensbewaring bij providers. De tools voor de formele security-scan waren niet beschikbaar. Dit document is een handmatige review, geen formeel scanresultaat.

## Welke gegevens verlaten de computer?

| Bestemming | Gegevens | Wanneer |
| --- | --- | --- |
| OpenRouter en de modelprovider | Gestructureerde spelwaarnemingen, mogelijke keuzes, doel en instructies; API-key naar OpenRouter als authenticatie | Jev `shadow` en `active`, bij geldige waarnemingen en beschikbare sleutel. `shadow` verstuurt wel degelijk gegevens. |
| Groq | JPG-beeld van het aan OCR aangeboden frame/uitsnede, OCR-instructie en authenticatie | Als `GROQ_API_KEY` is ingevuld. Kan tekst uit het spelbeeld bevatten. |
| Ingestelde remote webapp | Instance-ID, status en notificaties; ophalen van bediening/uitsluitingen | Als `WEB_APP_URL` is ingevuld. HTTPS wordt niet afgedwongen. |
| Telegram | Instance-ID en notificatietekst, bot-token als authenticatie | Als `TELEGRAM_BOT_TOKEN` is ingevuld. |
| PythonAnywhere | Gebruikersnaam en wachtwoord via HTTPS voor verlengen van hosting | Bij ingestelde PythonAnywhere-webapp en bijbehorende taak. |
| GitHub | Aanvragen voor publieke assetnamen/woordenboek; IP en normale requestmetadata | `get_vocab()`. Sommige cache-aanroepen voeren deze functie ook uit als een cachewaarde aanwezig is. |
| Google Fonts en Cloudflare CDN | Aanvragen voor stylesheets/fonts; IP en browsermetadata | Bij openen van GUI/webapp, ook de lokale desktop-GUI. |
| EasyOCR-modelhosting | Downloadaanvragen en requestmetadata | Lokale OCR kan bij ontbrekende modellen automatisch modellen downloaden. Niet tijdens deze review uitgevoerd. |

De onderzochte Jev-aanroep verstuurt geen screenshot, volledig configuratiebestand of Supercell-login. Geen expliciete verborgen analytics-SDK of heimelijke uploadfunctie aangetroffen in de onderzochte eigen code. Dit sluit gedrag van dependencies, emulator, spel of providers niet uit.

De huidige lokale `configs.py` is gecontroleerd zonder waarden van sleutels te tonen: webapp, Telegram en Groq zijn niet ingesteld. `JEV_MODE` ontbreekt daar en heeft daardoor standaardwaarde `off`. Dit zegt niets over een reeds draaiend proces of een andere geïnstalleerde build.

## Bevindingen

### Hoog: remote webapp zonder authenticatie

`app/app.py` heeft geen authenticatie op registratie, status, pauzeduur, uitsluitingen en notificaties. `CORS(app)` laat willekeurige origins toe. Lokale Flask-testclient-verzoeken zonder credentials kregen allemaal HTTP 200; gewijzigde waarden waren terug te lezen. Een aanvaller die de webapp kan bereiken kan gegevens lezen en botinstellingen wijzigen. De README adviseert bovendien port forwarding.

Aanpak: authenticatie en autorisatie op alle gevoelige routes, beperkende CORS, HTTPS en geen publieke blootstelling voordat dit is opgelost. De desktopserver gebruikt normaal Flask-loopbackbinding en is daarmee standaard niet op het LAN beschikbaar; lokale processen hebben echter geen authenticatie nodig.

### Hoog: opgeslagen HTML-injectie / XSS in webapp

Iedere bereikbare client kan tekst met HTML opslaan via `/instances/<id>/notify`. De notificatie-API bewaart die tekst intact. `app/templates/instance.html:243` en `:253` voegen `${notif.data}` via `innerHTML` toe. Instance-ID's worden eveneens via `innerHTML` weergegeven in `app/templates/home.html:46`, terwijl registratie geen HTML-beperking heeft. De desktopnotificatieweergave heeft dezelfde onveilige HTML-sink wanneer zij remote notificaties gebruikt.

Een lokale test bevestigde opslag en teruglezen van een onschadelijke testpayload; de uitvoeringsroute is vastgesteld uit de templates. Geen browserexploit uitgevoerd. Kwaadaardige event-handler-HTML kan script uitvoeren bij het tonen van de betreffende inhoud.

Aanpak: onbetrouwbare tekst via `textContent` invoegen en DOM-elementen afzonderlijk maken; CSP als aanvullende beperking.

### Middel: foutlogs kunnen geheimen bevatten

`src/log.py` gebruikt `logger.add()` zonder `diagnose=False`. Loguru kan daardoor bij `logger.exception()` argumenten en lokale variabelen in stacktraces opnemen. Een lokale reproductie met een fictief wachtwoord bevestigde dat het argument in de uitvoer verscheen. Dit bewijst het mechanisme; er is geen echte sleutel uit een bestaande log gehaald of getoond.

Jev logt normaal geen API-key en beperkt API-fouten tot het exceptiontype. Een ongehanteerde uitzondering elders kan via de algemene botlogger alsnog gevoelige waarden in bereikbare stackframes opnemen. Logs zijn lokale bestanden, maar delen daarvan kan gegevens prijsgeven.

Aanpak: `diagnose=False` voor alle Loguru-sinks, geheimen redigeren waar nodig en logs niet onbewerkt delen.

### Middel: remote ontwikkelserver luistert met debug aan

Direct starten van `app/app.py` gebruikt `host="0.0.0.0"` en `debug=True` op regel 209. Dat stelt de ontwikkelserver beschikbaar op netwerkinterfaces en kan foutinformatie/debugfunctionaliteit blootstellen. Werkelijke bereikbaarheid hangt af van firewall en hosting; uitvoering van debuggercode is niet getest of aangetoond.

Aanpak: debug uit, standaard loopback en een productie-WSGI-server achter gecontroleerde toegang als remote hosting nodig is.

## Lokale telemetry en macOS

Jev schrijft spelwaarnemingen, antwoorden, acties, instance-ID, tijdstippen en kosten naar roterende JSONL en naar de gewone botlog. Dit zijn lokale logs, geen apart telemetry-endpoint. Ook in `off` kunnen actie-/resultaatregels worden geschreven. Packaged builds gebruiken `~/.CoC_Bot/debug`; source-runs schrijven naar `debug/`. Er is nog geen aparte schakelaar om alle Jev-eventlogging uit te zetten.

De macOS-slaaphelper vraagt administratorrechten en wijzigt tijdelijk `pmset`-instellingen. De gelezen helper bevat geen netwerkverkeer. Accessibility-rechten zijn voor de lokale bediening. Emulator- en macOS-gedrag zijn hier niet op een echte Mac onderzocht.

## Validatie en aanbevolen instelling

De audit gebruikte uitsluitend lokale testclient-aanroepen en een fictief geheim; de webapp-cache werd naar een tijdelijke map omgeleid. Geen externe dienst aangeroepen en geen spelactie uitgevoerd.

Voor minimale gegevensdeling: remote webapp, Telegram en Groq leeg laten en Jev `off` zetten. Voor Jev blijven OpenRouter en de modelprovider noodzakelijk; behoud dan Groq uit zodat OCR lokaal blijft. De GUI/CDN- en woordenboekaanvragen zijn hiermee nog niet uitgeschakeld. Volledig offline gebruik vraagt lokale GUI-assets, een lokaal woordenboek en vooraf geïnstalleerde OCR-modellen.

De gevonden beveiligingsproblemen zijn in deze controle niet gewijzigd. Dependencies zijn niet vastgepind; hun volledige gedrag en actuele kwetsbaarheden zijn niet geverifieerd.
