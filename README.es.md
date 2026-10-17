# EMPORION — hechos de registro público para agentes que comercian

<!-- aicom-readme-badges -->
<p align="center">
  <a href="https://github.com/alexar76/emporion/actions/workflows/ci.yml"><img src="https://github.com/alexar76/emporion/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/alexar76/emporion/actions/workflows/pages.yml"><img src="https://github.com/alexar76/emporion/actions/workflows/pages.yml/badge.svg" alt="Pages deploy" /></a>
  <a href="https://emporion.modelmarket.dev/"><img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/live.svg" alt="Live service" /></a>
  <a href="https://alexar76.github.io/emporion/"><img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/landing.svg" alt="Landing" /></a>
  <a href="https://github.com/alexar76/emporion/pkgs/container/emporion"><img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/ghcr.svg" alt="GHCR package" /></a>
  <img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/python.svg" alt="Python >=3.11" />
  <img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/tests.svg" alt="tests" />
  <img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/aimarket.svg" alt="AIMarket v2" />
  <img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/signing.svg" alt="Ed25519 + ML-DSA signing" />
  <img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/i18n.svg" alt="Docs in 5 languages" />
  <a href="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/coverage.svg"><img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/coverage.svg" alt="Test coverage" /></a>
  <a href="https://github.com/alexar76/emporion/blob/main/LICENSE"><img src="https://raw.githubusercontent.com/alexar76/emporion/refs/heads/main/docs/badges/license.svg" alt="License: MIT" /></a>
</p>
<!-- /aicom-readme-badges -->

> 🌐 [English](README.md) · [Русский](README.ru.md) · **Español** · [Français](README.fr.md) · [中文](README.zh.md)

Un agente que compra, vende o paga necesita hechos que ningún modelo puede inventar: si este número
de IVA es válido, quién es esta empresa, cuál fue el tipo del euro aquel día, si este monedero está
en una lista de sanciones y si puedo probar que este documento existía ayer. EMPORION responde cada
uno desde el **registro público** —la Comisión Europea, GLEIF, el BCE, el Tesoro de EE. UU., la UE,
la ONU y Bitcoin— y firma cada respuesta junto con **de dónde viene, cuándo se obtuvo y el SHA-256
de lo que devolvió la fuente**.

*Emporion* (ἐμπόριον): el puesto comercial de una ciudad griega, donde los mercaderes se reunían y
liquidaban.

Desde la 0.2.0 responde también a las preguntas que vienen después: ¿está esta empresa en su
registro nacional, es válido su número EORI para la aduana, qué antigüedad tiene el dominio de la
tienda, qué día es el quinto día hábil en Baviera o en TARGET2? Y da a los agentes dos herramientas
que ningún modelo tiene: una **página web capturada como prueba** (anclada en Bitcoin) y un
**temporizador**, incluido un interruptor de hombre muerto, que llama al agente con un evento
firmado.

## Capacidades

| Capacidad | Precio | Qué responde | Fuente |
|---|---|---|---|
| `emporion.vat.check@v1` | $0.002 | ¿Es válido hoy este número de IVA de la UE? Nombre, dirección, hora de la consulta — y, si indica **su propio** número de IVA como solicitante, el **identificador de consulta** de VIES: prueba oficial de la comprobación a su nombre | EU VIES |
| `emporion.lei.lookup@v1` | $0.001 | ¿Quién es esta entidad jurídica? Por LEI (dígitos de control verificados localmente) o por nombre (candidatos ordenados): denominación, jurisdicción, forma jurídica, estado, direcciones, renovación, matrices directa y última | GLEIF (CC0) |
| `emporion.fx.rate@v1` | $0.001 | Tipo de referencia del euro para cualquier par en cualquier fecha desde 1999, el día del BCE al que corresponde, tipos cruzados a través del euro en Decimal, un importe redondeado a las unidades menores de la divisa | BCE |
| `emporion.sanctions.screen@v1` | $0.002 | ¿Está esta dirección de monedero o este nombre en una lista pública de sanciones? OFAC SDN (unas 510 direcciones de moneda digital), listas de la UE y la ONU, con la fecha y el SHA-256 de cada lista | OFAC · UE · ONU |
| `emporion.timestamp.stamp@v1` | $0.001 | Anclar un resumen SHA-256 en Bitcoin mediante los calendarios de OpenTimestamps; devuelve una prueba `.ots` estándar | OpenTimestamps |
| `emporion.timestamp.verify@v1` | $0.001 | Actualizar y verificar una prueba: confirmada cuando su resultado es igual a la raíz de Merkle de un bloque de Bitcoin cuya cabecera coincide en dos exploradores independientes | Bitcoin |
| `emporion.web.capture@v1` | $0.003 | Una página web como prueba: URL final, cada redirección, la IP, el estado, las cabeceras clave, el certificado TLS y el SHA-256 del cuerpo (y el cuerpo, hasta 512 KB); el SHA-256 del registro se ancla en Bitcoin | la propia página · OpenTimestamps |
| `emporion.domain.rdap@v1` | $0.001 | Quién registró este dominio y cuándo: creación, vencimiento, antigüedad en días, registrador, estado, servidores de nombres, DNSSEC — o `registered: false` | bootstrap de IANA → el registro del TLD |
| `emporion.company.lookup@v1` | $0.001 | ¿Existe esta empresa y sigue activa? Por número o nombre: nombre, estado, forma jurídica, fecha de constitución, dirección, número de IVA y los campos propios del registro | Brønnøysund (NO) · SIRENE/RNE (FR) · ARES (CZ) · PRH (FI) · Companies House (GB, con la clave del operador) |
| `emporion.eori.check@v1` | $0.002 | ¿Es válido este número EORI para la aduana de la UE? Hasta 10 a la vez; nombre y dirección si el operador lo consintió | Comisión Europea (EOS) |
| `emporion.calendar.check@v1` | $0.001 | Días hábiles en ~250 países (y regiones) o en un mercado (TARGET2, NYSE, LSE…): festivo, día hábil siguiente/anterior, fecha + N días hábiles, días entre fechas, los festivos de un año | python-holidays (sin red) |
| `emporion.timer.set@v1` | $0.002 | Un POST firmado a su callback https a una hora, o un interruptor de hombre muerto que se dispara si no se registra cada N segundos | — |
| `emporion.timer.checkin@v1` · `.cancel@v1` · `.status@v1` | gratis | Mantener vivo el interruptor, cancelar un temporizador, leer su estado (con el token del temporizador) | — |
| `emporion.sources@v1` | gratis | Licencia y atribución de cada fuente, las listas de sanciones que se tienen ahora, el último día del BCE | — |

```mermaid
flowchart LR
    A[Agente] -->|invoke + pago| H[Hub AIMarket]
    H -->|X-Provider-Signature obligatoria| E[EMPORION]
    E --> N{lista permitida<br/>por fuente}
    N --> V[VIES]
    N --> G[GLEIF]
    N --> C[BCE]
    N --> S[listas OFAC · UE · ONU<br/>actualizadas cada 6 h]
    N --> O[calendarios OpenTimestamps]
    N --> X[dos exploradores de Bitcoin]
    E -->|respuesta + pruebas:<br/>url · fetched_at · sha256| H
    H -->|recibo firmado| A
```

## Confianza, en breve

- **Pruebas en cada respuesta** — la URL de la fuente, la hora de obtención y el SHA-256 de los
  bytes devueltos, además de la licencia y la atribución de la fuente.
- **Dos firmas** — el recibo firmado de la pasarela (oracle-core, Ed25519, ML-DSA híbrido con
  `ORACLE_PQC=1`) y la `X-Provider-Signature` ligada a la petición que verifica el hub.
- **Una fuente que no puede responder no cuesta nada** — la respuesta es `ok:false`, y el hub no
  cobra nada por `ok:false`: un registro de IVA nacional caído, listas de sanciones sin cargar o
  con más de 48 h, menos de dos calendarios, exploradores en desacuerdo.
- **Las peticiones salientes se limitan a una lista por fuente**; las redirecciones se siguen a
  mano y solo hacia los hosts de esa misma fuente; el tamaño de las respuestas está acotado.
- **Las dos capacidades que llaman a una URL que elige quien llama** (captura web y callbacks de
  temporizadores) solo alcanzan direcciones públicas: http(s) en los puertos 80/443, cada
  dirección del nombre comprobada (nada de loopback, privadas, link-local, CGNAT ni metadatos), la
  conexión fijada a la dirección comprobada, cada redirección comprobada de nuevo y como mucho 20
  capturas de un mismo host por minuto.

## Ejemplos

```bash
H=https://emporion.modelmarket.dev
inv() { curl -s -X POST $H/ai-market/v2/invoke -H 'Content-Type: application/json' -d "$1"; }

inv '{"capability_id":"emporion.vat.check@v1","input":{"vat":"NL004495445B01","requester_vat":"DE811569869"}}'
inv '{"capability_id":"emporion.lei.lookup@v1","input":{"name":"Deutsche Bank"}}'
inv '{"capability_id":"emporion.fx.rate@v1","input":{"base":"USD","quote":"JPY","date":"2026-10-11","amount":"100"}}'
inv '{"capability_id":"emporion.sanctions.screen@v1","input":{"address":"0x…"}}'
inv '{"capability_id":"emporion.timestamp.stamp@v1","input":{"digest":"'"$(sha256sum contract.pdf | cut -d' ' -f1)"'"}}'
inv '{"capability_id":"emporion.web.capture@v1","input":{"url":"https://shop.example/terms"}}'
inv '{"capability_id":"emporion.domain.rdap@v1","input":{"domain":"shop.example"}}'
inv '{"capability_id":"emporion.company.lookup@v1","input":{"country":"FR","number":"552032534"}}'
inv '{"capability_id":"emporion.eori.check@v1","input":{"eori":"CZ00177041"}}'
inv '{"capability_id":"emporion.calendar.check@v1","input":{"market":"XECB","add_business_days":5}}'
inv '{"capability_id":"emporion.timer.set@v1","input":{"callback":"https://agent.example/hook","deadman_seconds":3600,"payload":{"release":"escrow-7"}}}'
```

A través del hub, las mismas llamadas se pagan y reciben recibo:
`POST https://modelmarket.dev/ai-market/v2/invoke` con `"product_id":"emporion"`.

### IVA: el identificador de consulta

VIES emite un identificador de consulta solo a un **número de IVA de la UE válido indicado como
solicitante**. Es la prueba del solicitante y la guarda el solicitante: pase su propio número en
`requester_vat` y el identificador de consulta de la respuesta será prueba, a su nombre, de que comprobó a
su contraparte en `checked_at`. Sin él la comprobación se hace igualmente; la respuesta explica
cómo obtener el número.

### Tipos de cambio: qué día

Un tipo «en» una fecha es la última publicación del BCE en esa fecha o antes, y la respuesta nombra
ese día (`ecb_date`): un domingo se valora al tipo del viernes, de forma visible. Una divisa que el
BCE dejó de cotizar (el RUB desde marzo de 2022) se rechaza en lugar de responder con un tipo de
hace años.

### Sanciones: una consulta, no una determinación

Un monedero se compara de forma exacta (direcciones EVM y bech32 sin distinguir mayúsculas). Un
nombre se compara como conjunto de palabras —orden, mayúsculas, tildes y formas jurídicas no
importan («DOE, John» es «John Doe»); una palabra con una errata cuenta 0,9 y nunca se lee como el
mismo nombre; y si todas las palabras pedidas están en un nombre más largo (un patronímico, un
segundo nombre) también coincide. El umbral por defecto es 0,85; cada coincidencia dice qué nombre
coincidió y su puntuación.

**Una coincidencia es motivo para mirar más de cerca; su ausencia no es una autorización.** Los
nombres se repiten y los alias son incompletos. Cada respuesta lo dice y nombra las listas usadas
con sus fechas de publicación y SHA-256. Una lista desactualizada se rechaza, no se usa.

### Sellos de tiempo

```mermaid
sequenceDiagram
    autonumber
    participant A as Agente
    participant E as EMPORION
    participant C as Calendarios OpenTimestamps
    participant B as Exploradores de Bitcoin (×2)
    A->>E: stamp {digest}
    E->>E: sha256(digest ‖ 16 bytes aleatorios) — los calendarios nunca ven el resumen
    E->>C: envío a los cuatro, al menos dos deben aceptar
    C-->>E: atestaciones pendientes
    E-->>A: prueba .ots (pendiente)
    Note over C: unas horas después la transacción agregada<br/>de los calendarios entra en un bloque de Bitcoin
    A->>E: verify {digest, proof}
    E->>C: actualización en cada calendario que nombra la prueba (solo permitidos)
    C-->>E: camino hasta el bloque
    E->>B: hash del bloque a la altura H y su cabecera — de ambos
    B-->>E: deben coincidir, y la cabecera debe dar el hash del bloque
    E->>E: resultado de la prueba == raíz de Merkle de la cabecera
    E-->>A: confirmado · existía a más tardar a la hora del bloque · prueba actualizada
```

La prueba es un archivo OpenTimestamps estándar: se verifica con cualquier cliente de
OpenTimestamps, sin EMPORION. El ejemplo de referencia (`hello-world.txt`) se verifica hasta el
bloque 358 391, 28-05-2015.

### Captura web: lo que decía la página

EMPORION obtiene la página una vez, como lo haría un navegador, y devuelve un `record`: la URL
pedida, la URL final, cada redirección con su estado e IP, la hora, el estado, las cabeceras que
dicen qué era la página (tipo, longitud, `Last-Modified`, `ETag`, `Date`, `Server`…), el
certificado TLS que presentó el servidor (sujeto, emisor, validez, nombres, SHA-256 del
certificado), el título y `body_sha256`. El cuerpo vuelve en `body_b64` si ocupa 512 KB o menos (el
límite de una página es 5 MB). `record_sha256` es el SHA-256 del registro en JSON con claves
ordenadas y separadores compactos, y se ancla en Bitcoin mediante OpenTimestamps — se verifica
después con `emporion.timestamp.verify@v1`. Un 404 es una captura (es lo que dijo la página); un
host inalcanzable o un certificado que no se verifica no cuesta nada.

### Temporizadores y el interruptor de hombre muerto

```mermaid
sequenceDiagram
    autonumber
    participant A as Agente
    participant E as EMPORION
    participant C as Callback del agente (https)
    A->>E: timer.set {callback, deadman_seconds: 3600, payload}
    E-->>A: timer_id + token (una vez)
    loop mientras el agente vive
        A->>E: timer.checkin {timer_id, token}
        E-->>A: due_at movido 3600 s adelante
    end
    Note over A: el agente se detiene
    E->>C: POST {event, signature} — Ed25519 (+ ML-DSA) sobre el evento
    C-->>E: 2xx (si no, reintento a 1, 5 y 30 min)
```

`at` (una hora ISO con zona) o `after_seconds` fijan en cambio una llamada única. El evento lleva el
id del temporizador, el tipo, las horas prevista y real, el intento y su payload (hasta 4 KB); la
firma es la clave de EMPORION de su manifiesto firmado, sobre el evento en JSON con claves
ordenadas y separadores compactos. El token se guarda solo como SHA-256. Un temporizador vive como
mucho 90 días, en un archivo SQLite del volumen de datos de EMPORION.

### Registros mercantiles, EORI, dominios, días hábiles

- **Los registros mercantiles** responden desde el propio registro: el Brønnøysund de Noruega
  (NLOD 2.0), SIRENE y el registro nacional de Francia mediante la API abierta del Estado (Licence
  Ouverte 2.0), el ARES checo, el PRH finlandés (CC BY 4.0) y — si el operador ha fijado
  `COMPANIES_HOUSE_API_KEY`, una clave gratuita — el Companies House británico (OGL v3.0); sin la
  clave no se ofrece GB. Los números se comprueban antes localmente (dígitos de control noruegos,
  checos y finlandeses; un SIRET francés se reduce a su SIREN). Estados: activa, cesada/disuelta/
  dada de baja, en quiebra, en liquidación, en reorganización.
- **EORI** viene del servicio EOS de la Comisión Europea; «no válido» es una respuesta.
- **RDAP** solo se pregunta a los servidores que el archivo bootstrap de IANA nombra para el TLD
  (solo https); un subdominio o una URL se reduce al nombre registrado preguntando al registro.
  Algunos dominios de país (`.de`, `.ru`…) aún no publican RDAP — se rechaza y no cuesta nada.
- **Los días hábiles** vienen de python-holidays, compilada en EMPORION: sin red, nada que se
  caiga; la respuesta indica la versión, porque un festivo declarado después no está en ella.

## Límites honestos

- VIES responde lo que responde el registro nacional en ese momento; algunos Estados no devuelven
  nombre ni dirección. EMPORION no guarda nada.
- GLEIF cubre las entidades que tienen LEI — muchas empresas pequeñas no lo tienen.
- Los tipos de referencia son informativos, no para operar.
- La consulta de sanciones es una búsqueda en tres listas públicas, no asesoramiento jurídico ni un
  programa de cumplimiento; no incluye listas de otras jurisdicciones.
- Un sello de tiempo prueba la existencia a más tardar a la hora de un bloque, no la autoría.
- Una captura muestra lo que el servidor respondió a EMPORION en ese momento; a otro visitante,
  desde otro país o con otras cookies puede mostrarle otra página. No afirma que el contenido sea
  cierto.
- Cada registro publica cosas distintas; por ahora se cubren los de cuatro países (cinco con la clave británica); la API del KRS polaco no respondió al probarla.
- Un temporizador se entrega al menos una vez si el callback responde 2xx en cuatro intentos; el
  receptor debe tratar un `timer_id` repetido con el mismo `due_at` como el mismo evento.

## Ejecutarlo

```bash
# desde este repositorio
docker build -f Dockerfile.standalone -t emporion .
docker run -d --name emporion -p 127.0.0.1:9351:9351 -v emporion-data:/data \
  -e EMPORION_PUBLIC_URL=http://127.0.0.1:9351 emporion
curl -s http://127.0.0.1:9351/health
```

En el monorepo [aicom](https://github.com/alexar76/aicom) lo mismo se ejecuta desde su raíz con
`docker compose -f emporion/docker-compose.yml up -d --build`. `EMPORION_PUBLIC_URL` es la dirección
por la que llegan los compradores; se escribe en el manifiesto firmado.

Producción, desde el monorepo aicom: `./scripts/deploy_emporion.sh --remote <host>` lo publica en
`https://modelmarket.dev/providers/emporion/` detrás del nginx existente (un fragmento, con copia de
seguridad y `nginx -t` antes de recargar), conserva la imagen en marcha como `emporion:prev` y
revierte una compilación que no arranca sana. Memoria en reposo ≈ 200 MB; el contenedor está
limitado a 768 MB. Se ejecuta como uid 10001. Su propia dirección es https://emporion.modelmarket.dev/:
la página para las personas en `/` y la misma API para los agentes en el resto de rutas
([`deploy/nginx/emporion.modelmarket.dev.conf`](https://github.com/alexar76/aicom/blob/main/deploy/nginx/emporion.modelmarket.dev.conf));
la ruta `/providers/emporion/` sigue siendo la dirección con la que federa el hub.

| Variable | Por defecto | Significado |
|---|---|---|
| `EMPORION_PUBLIC_URL` | `https://modelmarket.dev/providers/emporion` | URL base en el manifiesto |
| `EMPORION_PORT` | `9351` | puerto |
| `EMPORION_RATE_LIMIT` | `120` | invocaciones por minuto por cliente |
| `EMPORION_CORS_ORIGINS` | vacío (ningún origen de navegador) | lista CORS |
| `COMPANIES_HOUSE_API_KEY` | vacío (no se ofrece GB) | la clave gratuita de Companies House del operador |
| `EMPORION_TIMERS_DB` | `timers.sqlite` junto a la clave de firma | dónde se guardan los temporizadores |
| `ORACLE_PQC` | `1` en compose | firmas híbridas ML-DSA-65 |

Pruebas: `pip install -e "vendor/oracle-core[pqc]" -e '.[dev]' && pytest` (en el monorepo:
`-e ../oracles/core`) — 144 pruebas sobre extractos de respuestas reales, ninguna llega a una fuente
en vivo; en el monorepo la cadena canónica firmada se comprueba además byte a byte con la propia
función del hub.

## Fuentes y licencias

| Fuente | Licencia | Atribución en las respuestas |
|---|---|---|
| EU VIES | política de reutilización de la Comisión Europea (Decisión 2011/833/UE) | European Commission, VIES |
| GLEIF | CC0 1.0 | Global Legal Entity Identifier Foundation (GLEIF), CC0 |
| BCE | reproducción citando la fuente | Source: European Central Bank |
| OFAC SDN | obra del Gobierno de EE. UU. (dominio público) | U.S. Department of the Treasury, OFAC |
| Archivos de sanciones financieras de la UE | política de reutilización de la Comisión Europea | European Commission, FSF |
| Lista consolidada de la ONU | información pública de la ONU | United Nations Security Council Consolidated List |
| OpenTimestamps | calendarios públicos gratuitos | OpenTimestamps (opentimestamps.org) |
| EORI de la UE (EOS) | política de reutilización de la Comisión Europea | European Commission, EORI validation (EOS) |
| Brønnøysund | NLOD 2.0 | Brønnøysundregistrene, Enhetsregisteret (NLOD 2.0) |
| API Recherche d'entreprises | Licence Ouverte 2.0 (Etalab) | DINUM, API Recherche d'entreprises (INSEE SIRENE, INPI RNE) |
| ARES | datos abiertos de la administración checa | Ministerstvo financí ČR, ARES |
| PRH / YTJ | CC BY 4.0 | Finnish Patent and Registration Office (PRH), YTJ open data |
| Companies House (con clave) | Open Government Licence v3.0 | Contains public sector information from Companies House, OGL v3.0 |
| RDAP | datos públicos de registro (RFC 9083) | bootstrap RDAP de IANA y el registro del TLD |
| python-holidays | MIT | python-holidays (vacanza/holidays) |

Código: MIT — véase [LICENSE](LICENSE). La biblioteca de referencia de OpenTimestamps que usa es LGPL-3.0.
