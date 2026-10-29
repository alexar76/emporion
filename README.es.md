# SYMMARTYS — hechos de registro público para agentes que comercian

Local 0.5.0 rename: `aimarket-symmartys`, product `symmartys`, capabilities `symmartys.*`. See [migration](MIGRATION.md); new public addresses require a separate deployment.

![Python >=3.11](docs/badges/python.svg) ![Ed25519 + ML-DSA signing](docs/badges/signing.svg) ![MIT](docs/badges/license.svg)

> 🌐 [English](README.md) · [Русский](README.ru.md) · **Español** · [Français](README.fr.md) · [中文](README.zh.md)

Un agente que compra, vende o paga necesita hechos que ningún modelo puede inventar: si este número
de IVA es válido, quién es esta empresa, cuál fue el tipo del euro aquel día, si este monedero está
en una lista de sanciones y si puedo probar que este documento existía ayer. SYMMARTYS responde cada
uno desde el **registro público** —la Comisión Europea, GLEIF, el BCE, el Tesoro de EE. UU., la UE,
el Reino Unido y Bitcoin— y firma cada respuesta junto con **de dónde viene, cuándo se obtuvo y el SHA-256
de lo que devolvió la fuente**.

*Symmartys* (συμμάρτυς): un testigo conjunto o corroborante; una respuesta con fuentes que otra parte puede comprobar.

Desde la 0.2.0 responde también a las preguntas que vienen después: ¿está esta empresa en su
registro nacional, es válido su número EORI para la aduana, qué antigüedad tiene el dominio de la
tienda, qué día es el quinto día hábil en Baviera o en TARGET2? Y da a los agentes dos herramientas
que ningún modelo tiene: una **página web capturada como prueba** (anclada en Bitcoin) y un
**temporizador**, incluido un interruptor de hombre muerto, que llama al agente con un evento
firmado.

## Capacidades

| Capacidad | Precio | Qué responde | Fuente |
|---|---|---|---|
| `symmartys.vat.check@v1` | $0.002 | ¿Es válido hoy este número de IVA de la UE? Nombre, dirección, hora de la consulta — y, si indica **su propio** número de IVA como solicitante, el **identificador de consulta** de VIES: prueba oficial de la comprobación a su nombre | EU VIES |
| `symmartys.lei.lookup@v1` | $0.001 | ¿Quién es esta entidad jurídica? Por LEI (dígitos de control verificados localmente) o por nombre (candidatos ordenados): denominación, jurisdicción, forma jurídica, estado, direcciones, renovación, matrices directa y última | GLEIF (CC0) |
| `symmartys.fx.rate@v1` | $0.001 | Tipo de referencia del euro para cualquier par en cualquier fecha desde 1999, el día del BCE al que corresponde, tipos cruzados a través del euro en Decimal, un importe redondeado a las unidades menores de la divisa | BCE |
| `symmartys.sanctions.screen@v1` | $0.002 | ¿Está esta dirección de monedero o este nombre en una lista pública de sanciones? OFAC SDN (unas 1.050 direcciones de moneda digital), listas de la UE y del Reino Unido (las designaciones de la ONU a través de ellas, cada coincidencia con su número de la ONU), con la fecha y el SHA-256 de cada lista | OFAC · UE · Reino Unido |
| `symmartys.timestamp.stamp@v1` | $0.001 | Anclar un resumen SHA-256 en Bitcoin mediante los calendarios de OpenTimestamps; devuelve una prueba `.ots` estándar | OpenTimestamps |
| `symmartys.timestamp.verify@v1` | $0.001 | Actualizar y verificar una prueba: confirmada cuando su resultado es igual a la raíz de Merkle de la cabecera del bloque de Bitcoin que SYMMARTYS guarda tomada de la propia red Bitcoin (prueba de trabajo de cada cabecera comprobada, cadena confirmada por dos nodos) | Bitcoin |
| `symmartys.web.capture@v1` | $0.003 | Una página web como prueba: URL final, cada redirección, la IP, el estado, las cabeceras clave, el certificado TLS y el SHA-256 del cuerpo (y el cuerpo, hasta 512 KB); el SHA-256 del registro se ancla en Bitcoin | la propia página · OpenTimestamps |
| `symmartys.domain.rdap@v1` | $0.001 | Quién registró este dominio y cuándo: creación, vencimiento, antigüedad en días, registrador, estado, servidores de nombres, DNSSEC — o `registered: false` | bootstrap de IANA → el registro del TLD |
| `symmartys.company.lookup@v1` | $0.001 | ¿Existe esta empresa y sigue activa? Por número o nombre: nombre, estado, forma jurídica, fecha de constitución, dirección, número de IVA y los campos propios del registro | Brønnøysund (NO) · SIRENE/RNE (FR) · ARES (CZ) · PRH (FI) · Companies House (GB, con la clave del operador) |
| `symmartys.eori.check@v1` | $0.002 | ¿Es válido este número EORI para la aduana de la UE? Hasta 10 a la vez; nombre y dirección si el operador lo consintió | Comisión Europea (EOS) |
| `symmartys.calendar.check@v1` | $0.001 | Días hábiles en ~250 países (y regiones) o en un mercado (TARGET2, NYSE, LSE…): festivo, día hábil siguiente/anterior, fecha + N días hábiles, días entre fechas, los festivos de un año | python-holidays (sin red) |
| `symmartys.timer.set@v1` | $0.002 | Un POST firmado a su callback https a una hora, o un interruptor de hombre muerto que se dispara si no se registra cada N segundos | — |
| `symmartys.timer.checkin@v1` · `.cancel@v1` · `.status@v1` | gratis | Mantener vivo el interruptor, cancelar un temporizador, leer su estado (con el token del temporizador) | — |
| `symmartys.sources@v1` | gratis | Licencia y atribución de cada fuente, las listas de sanciones que se tienen ahora, el último día del BCE | — |

```mermaid
flowchart LR
    A[Agente] -->|invoke + pago| H[Hub AIMarket]
    H -->|X-Provider-Signature obligatoria| E[SYMMARTYS]
    E --> N{lista permitida<br/>por fuente}
    N --> V[VIES]
    N --> G[GLEIF]
    N --> C[BCE]
    N --> S[listas OFAC · UE · Reino Unido<br/>actualizadas cada 6 h]
    N --> O[calendarios OpenTimestamps]
    E --> X[red P2P de Bitcoin<br/>cabeceras · prueba de trabajo comprobada]
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
  con más de 48 h, menos de dos calendarios, un bloque al que la cadena de cabeceras aún no llega.
- **Las peticiones salientes se limitan a una lista por fuente**; las redirecciones se siguen a
  mano y solo hacia los hosts de esa misma fuente; el tamaño de las respuestas está acotado.
- **Las dos capacidades que llaman a una URL que elige quien llama** (captura web y callbacks de
  temporizadores) solo alcanzan direcciones públicas: http(s) en los puertos 80/443, cada
  dirección del nombre comprobada (nada de loopback, privadas, link-local, CGNAT ni metadatos), la
  conexión fijada a la dirección comprobada, cada redirección comprobada de nuevo y como mucho 20
  capturas de un mismo host por minuto.

## Ejemplos

```bash
H=https://symmartys.modelmarket.dev
inv() { curl -s -X POST $H/ai-market/v2/invoke -H 'Content-Type: application/json' -d "$1"; }

inv '{"capability_id":"symmartys.vat.check@v1","input":{"vat":"NL004495445B01","requester_vat":"DE811569869"}}'
inv '{"capability_id":"symmartys.lei.lookup@v1","input":{"name":"Deutsche Bank"}}'
inv '{"capability_id":"symmartys.fx.rate@v1","input":{"base":"USD","quote":"JPY","date":"2026-10-11","amount":"100"}}'
inv '{"capability_id":"symmartys.sanctions.screen@v1","input":{"address":"0x…"}}'
inv '{"capability_id":"symmartys.timestamp.stamp@v1","input":{"digest":"'"$(sha256sum contract.pdf | cut -d' ' -f1)"'"}}'
inv '{"capability_id":"symmartys.web.capture@v1","input":{"url":"https://shop.example/terms"}}'
inv '{"capability_id":"symmartys.domain.rdap@v1","input":{"domain":"shop.example"}}'
inv '{"capability_id":"symmartys.company.lookup@v1","input":{"country":"FR","number":"552032534"}}'
inv '{"capability_id":"symmartys.eori.check@v1","input":{"eori":"CZ00177041"}}'
inv '{"capability_id":"symmartys.calendar.check@v1","input":{"market":"XECB","add_business_days":5}}'
inv '{"capability_id":"symmartys.timer.set@v1","input":{"callback":"https://agent.example/hook","deadman_seconds":3600,"payload":{"release":"escrow-7"}}}'
```

A través del hub, las mismas llamadas se pagan y reciben recibo:
`POST https://modelmarket.dev/ai-market/v2/invoke` con `"product_id":"symmartys"`.

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

**Las designaciones de la ONU llegan a través de las listas del Reino Unido y de la UE.** El archivo
del propio Consejo de Seguridad no tiene licencia de reutilización, así que SYMMARTYS no lo lee. La
lista del Reino Unido (Open Government Licence v3.0) da a cada designación de la ONU que aplica su
número de la ONU, como hace el archivo de la UE para algunas: una coincidencia lleva `un_ref`, y
`lists: ["UN"]` consulta solo las entradas del Reino Unido y de la UE que lo tienen. El 17-10-2026
las tres listas juntas contenían las 1010 entradas de la ONU (991 por número en la lista británica,
el resto por nombre en las de la UE y OFAC). Las decisiones más recientes llegan con el retraso con
que el Reino Unido y la UE las aplican, normalmente días.

### Sellos de tiempo

```mermaid
sequenceDiagram
    autonumber
    participant A as Agente
    participant E as SYMMARTYS
    participant C as Calendarios OpenTimestamps
    participant B as Nodos de Bitcoin (P2P, ×2)
    A->>E: stamp {digest}
    E->>E: sha256(digest ‖ 16 bytes aleatorios) — los calendarios nunca ven el resumen
    E->>C: envío a los cuatro, al menos dos deben aceptar
    C-->>E: atestaciones pendientes
    E-->>A: prueba .ots (pendiente)
    Note over C: unas horas después la transacción agregada<br/>de los calendarios entra en un bloque de Bitcoin
    A->>E: verify {digest, proof}
    E->>C: actualización en cada calendario que nombra la prueba (solo permitidos)
    C-->>E: camino hasta el bloque
    E->>B: getheaders — toda la cadena, guardada y actualizada
    B-->>E: prueba de trabajo y dificultad de cada cabecera comprobadas, un segundo nodo coincide
    E->>E: resultado de la prueba == raíz de Merkle de la cabecera
    E-->>A: confirmado · existía a más tardar a la hora del bloque · prueba actualizada
```

La prueba es un archivo OpenTimestamps estándar: se verifica con cualquier cliente de
OpenTimestamps, sin SYMMARTYS. El ejemplo de referencia (`hello-world.txt`) se verifica hasta el
bloque 358 391, 28-05-2015.

### Captura web: lo que decía la página

SYMMARTYS obtiene la página una vez, como lo haría un navegador, y devuelve un `record`: la URL
pedida, la URL final, cada redirección con su estado e IP, la hora, el estado, las cabeceras que
dicen qué era la página (tipo, longitud, `Last-Modified`, `ETag`, `Date`, `Server`…), el
certificado TLS que presentó el servidor (sujeto, emisor, validez, nombres, SHA-256 del
certificado), el título y `body_sha256`. El cuerpo vuelve en `body_b64` si ocupa 512 KB o menos (el
límite de una página es 5 MB). `record_sha256` es el SHA-256 del registro en JSON con claves
ordenadas y separadores compactos, y se ancla en Bitcoin mediante OpenTimestamps — se verifica
después con `symmartys.timestamp.verify@v1`. Un 404 es una captura (es lo que dijo la página); un
host inalcanzable o un certificado que no se verifica no cuesta nada.

### Temporizadores y el interruptor de hombre muerto

```mermaid
sequenceDiagram
    autonumber
    participant A as Agente
    participant E as SYMMARTYS
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
firma es la clave de SYMMARTYS de su manifiesto firmado, sobre el evento en JSON con claves
ordenadas y separadores compactos. El token se guarda solo como SHA-256. Un temporizador vive como
mucho 90 días, en un archivo SQLite del volumen de datos de SYMMARTYS.

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
- **Cortesía con RDAP.** Las condiciones de los registros prohíben las consultas automáticas masivas y
  el reempaquetado, así que SYMMARTYS pregunta a cada registro como mucho 30 veces por minuto,
  guarda cada respuesta 24 horas (una hora para «no registrado»; la respuesta en caché dice
  `cached: true` y conserva la hora original) y transmite los avisos del propio registro — sus
  condiciones de uso entre ellos — en `registry_terms`.
- **Datos personales.** Los registros incluyen también empresarios individuales, cuyos datos son
  personales sea cual sea la licencia del registro. Cada respuesta lleva `personal_data`: la
  finalidad (verificar a una contraparte), la base (interés legítimo, art. 6.1.f RGPD) y la
  conservación (SYMMARTYS no guarda copia; su registro de llamadas solo guarda un hash de la entrada).
- **Los días hábiles** vienen de python-holidays, compilada en SYMMARTYS: sin red, nada que se
  caiga; la respuesta indica la versión, porque un festivo declarado después no está en ella.

## Límites honestos

- VIES responde lo que responde el registro nacional en ese momento; algunos Estados no devuelven
  nombre ni dirección. SYMMARTYS no guarda nada.
- GLEIF cubre las entidades que tienen LEI — muchas empresas pequeñas no lo tienen.
- Los tipos de referencia son informativos, no para operar.
- La consulta de sanciones es una búsqueda en tres listas públicas, no asesoramiento jurídico ni un
  programa de cumplimiento; no incluye listas de otras jurisdicciones.
- Un sello de tiempo prueba la existencia a más tardar a la hora de un bloque, no la autoría.
- Una captura muestra lo que el servidor respondió a SYMMARTYS en ese momento; a otro visitante,
  desde otro país o con otras cookies puede mostrarle otra página. No afirma que el contenido sea
  cierto.
- Cada registro publica cosas distintas; por ahora se cubren los de cuatro países (cinco con la clave británica); la API del KRS polaco no respondió al probarla.
- Un temporizador se entrega al menos una vez si el callback responde 2xx en cuatro intentos; el
  receptor debe tratar un `timer_id` repetido con el mismo `due_at` como el mismo evento.

## Ejecutarlo

```bash
# desde este repositorio
docker build -f symmartys/Dockerfile -t symmartys .
docker run -d --name symmartys -p 127.0.0.1:9351:9351 -v symmartys-data:/data \
  -e SYMMARTYS_PUBLIC_URL=http://127.0.0.1:9351 symmartys
curl -s http://127.0.0.1:9351/health
```

En el monorepo [aicom](https://github.com/alexar76/aicom) lo mismo se ejecuta desde su raíz con
`SYMMARTYS_VOLUME_NAME=symmartys-data docker compose -f symmartys/docker-compose.yml up -d --build` ([volume migration](MIGRATION.md); fresh installs first run `docker volume create symmartys-data`). `SYMMARTYS_PUBLIC_URL` es la dirección
por la que llegan los compradores; se escribe en el manifiesto firmado.

Producción, desde el monorepo aicom: `./scripts/deploy_symmartys.sh --remote <host>` lo publica en
`https://modelmarket.dev/providers/symmartys/` detrás del nginx existente (un fragmento, con copia de
seguridad y `nginx -t` antes de recargar), conserva la imagen en marcha como `symmartys:prev` y
revierte una compilación que no arranca sana. Memoria en reposo ≈ 200 MB; el contenedor está
limitado a 768 MB. Se ejecuta como uid 10001. Su propia dirección es https://symmartys.modelmarket.dev/:
la página para las personas en `/` y la misma API para los agentes en el resto de rutas
([`deploy/nginx/symmartys.modelmarket.dev.conf`](../deploy/nginx/symmartys.modelmarket.dev.conf));
la ruta `/providers/symmartys/` sigue siendo la dirección con la que federa el hub.

| Variable | Por defecto | Significado |
|---|---|---|
| `SYMMARTYS_PUBLIC_URL` | `https://modelmarket.dev/providers/symmartys` | URL base en el manifiesto |
| `SYMMARTYS_PORT` | `9351` | puerto |
| `SYMMARTYS_RATE_LIMIT` | `120` | invocaciones por minuto por cliente |
| `SYMMARTYS_CORS_ORIGINS` | vacío (ningún origen de navegador) | lista CORS |
| `COMPANIES_HOUSE_API_KEY` | vacío (no se ofrece GB) | la clave gratuita de Companies House del operador |
| `SYMMARTYS_TIMERS_DB` | `timers.sqlite` junto a la clave de firma | dónde se guardan los temporizadores |
| `ORACLE_PQC` | `1` en compose | firmas híbridas ML-DSA-65 |

Pruebas: `pip install -e "vendor/oracle-core[pqc]" -e '.[dev]' && pytest` (en el monorepo:
`-e ../oracles/core`) — 175 pruebas sobre extractos de respuestas reales, ninguna llega a una fuente
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
| Lista de sanciones del Reino Unido (FCDO) | Open Government Licence v3.0 | Contains public sector information licensed under the Open Government Licence v3.0 (UK Sanctions List, FCDO) |
| OpenTimestamps | calendarios públicos gratuitos | OpenTimestamps (opentimestamps.org) |
| Cabeceras de bloques de Bitcoin | datos públicos de la cadena, obtenidos de nodo a nodo | Bitcoin network |
| EORI de la UE (EOS) | política de reutilización de la Comisión Europea | European Commission, EORI validation (EOS) |
| Brønnøysund | NLOD 2.0 | Brønnøysundregistrene, Enhetsregisteret (NLOD 2.0) |
| API Recherche d'entreprises | Licence Ouverte 2.0 (Etalab) | DINUM, API Recherche d'entreprises (INSEE SIRENE, INPI RNE) |
| ARES | datos abiertos de la administración checa | Ministerstvo financí ČR, ARES |
| PRH / YTJ | CC BY 4.0 | Finnish Patent and Registration Office (PRH), YTJ open data |
| Companies House (con clave) | Open Government Licence v3.0 | Contains public sector information from Companies House, OGL v3.0 |
| RDAP | datos públicos de registro (RFC 9083) | bootstrap RDAP de IANA y el registro del TLD |
| python-holidays | MIT | python-holidays (vacanza/holidays) |

Código: MIT — véase [LICENSE](LICENSE). La biblioteca de referencia de OpenTimestamps que usa es LGPL-3.0.
