# Typed `ActionResult` API: mögliche Refactorings

## Ausgangslage

Die aktuelle API ist typisiert, aber an den Return-Stellen unnötig laut:

```python
def get_weather(city: str) -> ActionResult[WeatherResult]:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return ActionResult[WeatherResult].fail(f"Unknown city: {city!r}")
    return ActionResult[WeatherResult].success(WeatherResult(city=city, temp_c=temp_c))
```

`WeatherResult` muss dreimal genannt werden. Besonders bei langen oder
verschachtelten Result-Typen wird das schnell unleserlich.

Eine gute Lösung sollte:

- `result` statisch typisieren;
- Erfolgs- und Fehlerfälle ergonomisch erzeugen;
- mit der Error-Boundary-Middleware funktionieren;
- projektspezifische optionale Felder erlauben, ohne sie im Toolkit vorzugeben;
- möglichst wenige unmögliche Zustände zulassen;
- unter Python 3.12 moderne PEP-695-Syntax verwenden;
- bei dynamischem Dispatch über einen Tool-Namen ehrlich bleiben: Eine heterogene
  Registry kann auf dieser Ebene keinen einzelnen konkreten Payload-Typ ableiten.

## Möglichkeit 1: spezialisierten Typ einmal lokal binden

```python
WeatherActionResult = ActionResult[WeatherResult]


def get_weather(city: str) -> WeatherActionResult:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return WeatherActionResult.fail(f"Unknown city: {city!r}")
    return WeatherActionResult.success(WeatherResult(city=city, temp_c=temp_c))
```

### Vorteile

- Kleinste Änderung; die Toolkit-API muss nicht umgebaut werden.
- `WeatherResult` wird nur einmal genannt.
- Pydantic validiert weiterhin das konkrete Result.
- Die Error Boundary und `Tools(result_type=...)` bleiben unverändert.
- Ein Alias kann später durch eine echte Unterklasse ersetzt werden.

### Nachteile

- Der Alias ist zusätzlicher lokaler Boilerplate.
- Die moderne `type WeatherActionResult = ...`-Syntax eignet sich hier nicht:
  Sie erzeugt ein `TypeAliasType` und stellt die Klassenmethoden `success()` und
  `fail()` nicht als Konstruktor-API bereit. Für diesen Zweck wäre bewusst die
  Zuweisung `WeatherActionResult = ActionResult[WeatherResult]` nötig.
- `ok`, `result` und `error` bilden weiterhin ein einzelnes Modell, in dem
  theoretisch widersprüchliche Zustände direkt konstruiert werden können.

### Einschätzung

Die beste kurzfristige Lösung. Sie beseitigt das konkrete Ergonomieproblem ohne
einen großen API-Umbau.

## Möglichkeit 2: eine konkrete Result-Unterklasse pro Payload

```python
class WeatherActionResult(ActionResult[WeatherResult]):
    pass


def get_weather(city: str) -> WeatherActionResult:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return WeatherActionResult.fail(f"Unknown city: {city!r}")
    return WeatherActionResult.success(WeatherResult(city=city, temp_c=temp_c))
```

Projektspezifische Felder können direkt ergänzt werden:

```python
class WeatherActionResult(ActionResult[WeatherResult]):
    provider: str | None = None
    cache_hit: bool | None = None
```

### Vorteile

- Sehr gut lesbare Tool-Signatur und Return-Stellen.
- Projektspezifische Felder sind vollständig typisiert.
- IDE-Autovervollständigung und Pydantic-Validierung funktionieren.
- `isinstance()` kann mit der konkreten Unterklasse sicher verwendet werden.
- Passt bereits zum vorhandenen `result_type`-Mechanismus.

### Nachteile

- Für jeden Payload-Typ entsteht eine kleine Klasse.
- Wenn keine projektspezifischen Felder benötigt werden, ist `pass` nur
  Boilerplate.
- Die Factory-Methoden akzeptieren projektspezifische Felder aktuell über
  `**fields: object`; Namen und Typen werden dadurch zur Laufzeit, aber nicht
  vollständig am Methodenaufruf statisch geprüft. Der direkte Pydantic-Konstruktor
  der Unterklasse ist statisch präziser.

### Einschätzung

Die beste Variante, sobald ein Projekt tatsächlich eigene Result-Felder benötigt.
Für einfache Resultate ist Möglichkeit 1 kompakter.

## Möglichkeit 3: freie Funktionen `success()` und `failure()`

Gewünschte Verwendung:

```python
def get_weather(city: str) -> ActionResult[WeatherResult]:
    if city.lower() not in _KNOWN_CITIES:
        return failure(f"Unknown city: {city!r}")
    return success(WeatherResult(city=city, temp_c=18.0))
```

`success()` kann seinen generischen Typ problemlos aus dem Argument ableiten:

```python
def success[ResultT](result: ResultT) -> ActionResult[ResultT]: ...
```

Bei `failure()` existiert dagegen kein Wert, aus dem `ResultT` abgeleitet werden
kann. Ein vermeintlich generisches
`failure[WeatherResult](...)` ist in Python keine aufrufbare Syntax für Funktionen.
Ein Rückgabetyp wie `ActionResult[Never]` wäre nur dann sauber zuweisbar, wenn
`ActionResult` kovariant wäre. Das ist für ein Pydantic-Modell mit öffentlichem
`result`-Feld nicht zuverlässig und sollte nicht durch Typechecker-spezifische
Tricks erzwungen werden.

### Einschätzung

Mit dem derzeitigen einzelnen `ActionResult`-Modell nicht vollständig typsicher.
Nur `success()` zu ergänzen würde eine asymmetrische API erzeugen. Daher nicht
empfohlen.

## Möglichkeit 4: `Success`/`Failure` als diskriminierte Union

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ActionResultBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionSuccess[ResultT](ActionResultBase):
    ok: Literal[True] = True
    result: ResultT


class ActionFailure(ActionResultBase):
    ok: Literal[False] = False
    error: str


type ActionResult[ResultT] = ActionSuccess[ResultT] | ActionFailure


def success[ResultT](result: ResultT) -> ActionSuccess[ResultT]:
    return ActionSuccess(result=result)


def failure(error: str | Exception) -> ActionFailure:
    return ActionFailure(error=str(error))
```

Die Tool-Implementierung wäre sehr kompakt:

```python
def get_weather(city: str) -> ActionResult[WeatherResult]:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return failure(f"Unknown city: {city!r}")
    return success(WeatherResult(city=city, temp_c=temp_c))
```

### Vorteile

- Beste Ergonomie an den Return-Stellen.
- Vollständig typisierte `success()`-Factory durch Typinferenz.
- `failure()` benötigt keinen unbekannten Payload-Typ.
- `ok` ist ein echter Discriminator. Typechecker können nach `if result.ok:`
  zwischen Success und Failure unterscheiden.
- Unmögliche Zustände verschwinden:
  Ein Erfolg hat kein `error`, ein Fehler hat kein optionales Erfolgs-`result`.
- Das JSON bleibt einfach und eindeutig.

### Nachteile

- Größter Breaking Change.
- `ActionResult` wäre ein Type-Alias und keine konkrete Klasse mehr.
  `ActionResult.success(...)`, `ActionResult.fail(...)` und
  `isinstance(value, ActionResult)` wären nicht mehr möglich.
- Middleware und `Tools` müssten gegen `ActionResultBase` beziehungsweise einen
  Result-Factory-Vertrag arbeiten.
- Projektspezifische Top-Level-Felder müssen sowohl für Success als auch Failure
  modelliert werden:

  ```python
  class ProjectSuccess[ResultT](ActionSuccess[ResultT]):
      trace_id: str | None = None


  class ProjectFailure(ActionFailure):
      trace_id: str | None = None


  type ProjectActionResult[ResultT] = ProjectSuccess[ResultT] | ProjectFailure
  ```

- Eine projektspezifische Error Boundary braucht eine konfigurierbare Factory,
  die `ProjectFailure` erzeugt. Nur ein einzelnes `result_type` reicht dann nicht
  mehr.

### Einschätzung

Typentheoretisch und ergonomisch die beste langfristige API. Sie lohnt sich, wenn
wir bereit sind, Result-Erzeugung, Middleware-Verträge und Projekterweiterung
gemeinsam neu zu schneiden.

## Möglichkeit 5: Factory-Objekt beziehungsweise `ResultSpec`

```python
weather_result = ResultSpec(WeatherResult)


def get_weather(city: str) -> ActionResult[WeatherResult]:
    if city.lower() not in _KNOWN_CITIES:
        return weather_result.fail(f"Unknown city: {city!r}")
    return weather_result.success(WeatherResult(city=city, temp_c=18.0))
```

### Vorteile

- Der Payload-Typ wird nur einmal angegeben.
- Eine Factory könnte projektspezifische Defaults ergänzen.
- Error Boundary und Tools könnten dieselbe Factory verwenden.

### Nachteile

- Python-Typechecker können einen zur Laufzeit übergebenen Typ nicht immer so
  präzise in den generischen Rückgabetyp eines Factory-Objekts übertragen wie
  eine normale parametrisierte Klasse.
- Zusätzliche Abstraktion und zusätzlicher Laufzeitgegenstand.
- Weniger idiomatisch als ein Klassenalias oder eine diskriminierte Union.

### Einschätzung

Mehr Mechanik als Nutzen. Nicht empfohlen, solange Möglichkeit 1 oder 2 genügt.

## Möglichkeit 6: erwartete Tool-Fehler als Exceptions

```python
def get_weather(city: str) -> WeatherResult:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        raise ToolError(f"Unknown city: {city!r}")
    return WeatherResult(city=city, temp_c=temp_c)
```

`Tools` würde den normalen Wert als Erfolg verpacken und die Error Boundary
übersetzt `ToolError` in ein fehlgeschlagenes Resultat.

### Vorteile

- Die Tool-Funktion hat die sauberste fachliche Signatur.
- Kein `ActionResult[...]` in der Tool-Implementierung.
- Zentralisierte Fehlerübersetzung.

### Nachteile

- Erwartete fachliche Fehler werden als Exceptions modelliert.
- Führt wieder eine spezielle `ToolError`-Semantik in den Toolkit-Kern ein.
- Projektspezifische Fehlerdaten müssen an der Exception hängen oder später
  rekonstruiert werden.
- Widerspricht dem Ziel, dem Projekt möglichst wenig Fehlerpolitik vorzugeben.

### Einschätzung

Ergonomisch attraktiv, architektonisch für dieses Toolkit aber zu opinionated.

## Empfehlung

### Kurzfristig

Das bestehende generische Modell behalten und den konkreten Typ einmal binden:

```python
WeatherActionResult = ActionResult[WeatherResult]


def get_weather(city: str) -> WeatherActionResult:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return WeatherActionResult.fail(f"Unknown city: {city!r}")
    return WeatherActionResult.success(WeatherResult(city=city, temp_c=temp_c))
```

Sobald projektspezifische Felder benötigt werden, wird daraus eine echte Klasse:

```python
class WeatherActionResult(ActionResult[WeatherResult]):
    provider: str | None = None
```

Diese Lösung ist klein, robust und kompatibel mit der bestehenden Error Boundary.

### Langfristig

Wenn die Result-API ohnehin noch brechen darf, ist die diskriminierte Union aus
`ActionSuccess[ResultT]` und `ActionFailure` die stärkste Lösung. Sie erzeugt die
schönste Aufrufsyntax und die präziseste Typverengung. Vor einer Umsetzung muss
aber der Erweiterungspunkt neu festgelegt werden:

- entweder getrennte projektspezifische Success-/Failure-Unterklassen;
- oder ein projektspezifischer, typisierter Metadatenwert statt beliebiger
  zusätzlicher Top-Level-Felder;
- plus eine Result-Factory für die Error Boundary.

## Entscheidungsgrundlage

Die zentrale Abwägung lautet:

- Ist minimale API und einfache projektspezifische Vererbung wichtiger?
  Dann Möglichkeit 1/2.
- Ist maximale Typpräzision und die schönste Tool-Implementierung wichtiger?
  Dann Möglichkeit 4 mit bewusst größerem Refactoring.

## Entscheidung

Die Library-API bleibt unverändert. Anwendungen verwenden:

- einen lokalen Alias wie `WeatherActionResult = ActionResult[WeatherResult]`,
  wenn nur der Payload-Typ spezialisiert wird;
- eine konkrete oder generische Unterklasse, wenn das Projekt zusätzliche
  typisierte Felder benötigt.

Beide Muster werden direkt an `ActionResult` und in der README dokumentiert.
