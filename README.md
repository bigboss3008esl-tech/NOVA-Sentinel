# NOVA Sentinel

Ein kleines Tool, das einen selbst gewaehlten Bildschirmbereich per Screenshot
und OCR ausliest (z. B. eine Item-Anzahl oder das Traggewicht in einem Spiel)
und warnt, wenn ein Wert eine Schwelle unter- bzw. ueberschreitet. Steuerung
und Anzeige laufen ueber ein kleines Web-Dashboard, das im eigenen WLAN
erreichbar ist (z. B. vom Handy aus).

**von Grigorios Gkisios ~ Hobby Developer**

Bei der Entwicklung habe ich zusaetzlich ein KI-Werkzeug (Claude von Anthropic)
genutzt, ganz normal in der heutigen Zeit. Konzept, Anforderungen, Architektur-
Entscheidungen, Fehlersuche und das komplette Testen kamen von mir, die KI hat
beim Schreiben des Codes nach meinen Vorgaben unterstuetzt.

---

## Funktionen

- Live-Ueberwachung von zwei Werten gleichzeitig (z. B. Item-Bestand und Traggewicht)
- Interaktive Zielauswahl per Rechteck-Ziehen ("TARGET LOCK"), kein manuelles
  Eintragen von Bildschirmkoordinaten noetig
- Ampel-Farben und akustische Warnung bei kritischen Werten, mit
  unterschiedlichen Toenen je nach Ereignis
- Web-Dashboard (per Browser erreichbar, keine App-Installation noetig)
- Optional HTTPS mit selbstsigniertem Zertifikat

## Installation

```
pip install mss pillow pytesseract cryptography
```

Zusaetzlich wird [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
als separates Programm benoetigt (nicht ueber pip installierbar).

## Start

```
python zahl_warner_app.py
```

Die angezeigte Adresse im Browser (PC oder Handy im selben WLAN) oeffnen.

---

## Datenschutz / Verarbeitung von Daten

Dieses Tool sammelt, speichert oder ueberträgt **keinerlei Daten an Dritte
oder an den Entwickler**. Deshalb wird bewusst auf eine separate
Datenschutzerklaerung verzichtet:

- Alle Screenshots und erkannten Werte werden **ausschliesslich lokal auf dem
  eigenen Rechner** verarbeitet (Texterkennung per Tesseract, ebenfalls lokal).
- Die Web-Oberflaeche ist **nur innerhalb des eigenen Heimnetzwerks (WLAN)**
  erreichbar, es gibt keinen externen Server und keine Cloud-Anbindung.
- Es werden **keine Accountdaten, Passwoerter oder personenbezogene Daten**
  verarbeitet oder gespeichert.
- Der Entwickler hat **keinerlei Zugriff** auf die Daten oder Nutzung anderer
  Personen, die dieses Tool verwenden.

Da keine Datenverarbeitung im Sinne der DSGVO durch den Anbieter/Entwickler
stattfindet (das Tool ist reine, lokal laufende Software ohne
Server-Komponente), ist keine Datenschutzerklaerung erforderlich. Dies ist
keine Rechtsberatung, sondern eine transparente Einordnung der
Funktionsweise.

## Hinweis zu Nutzungsbedingungen von Drittanbieter-Spielen

Dieses Tool interagiert nicht mit Spielprozessen (keine Eingaben, kein
Speicherzugriff, keine Client-Modifikation) und liest ausschliesslich
eigene Bildschirmbereiche per Screenshot aus. Trotzdem koennen die
Nutzungsbedingungen einzelner Spiele oder Plattformen zusaetzliche Software
generell einschraenken. Es liegt in der Verantwortung der nutzenden Person,
dies vor dem Einsatz mit dem jeweiligen Anbieter zu klaeren.

## Lizenz

Nutzung auf eigene Verantwortung. Kein Support- oder Gewaehrleistungsanspruch.
