# Plan: indicativo "Otro…" y formato de los honorarios en visitas

Fecha: 2026-11-03. Rama `63-agregar-moes`. Lo ejecuta Claude; el commit y el push los hace el usuario.

## 1. Situación actual

- **Teléfono del visitante.** Los formularios de alta (`properties/visit_form.html`) y edición
  (`visits/edit_form.html`) llevan un selector propio con los 16 países de
  `PhoneCountryCodes.OPTIONS` y sin "Otro…". La ruta concatena `indicativo + dígitos` sin validar
  la longitud. Los formularios de comprador ya usan el macro `phone_field`
  (`components/phone_macros.html` + `/static/js/phone-field.js`) con "Otro…" y el servidor compone
  el número con `app.core.phone.phone_from_form` (PLAN_TELEFONO_COMPRADOR.md). La deuda "Visitas
  aún no usa el macro" estaba apuntada.
- **Honorarios.** Se guardan como texto tal cual se escriben (`2500`, `2.500`, `2,5%`). "1.2" y
  "1,2" se aceptan los dos y se muestran tal cual en la ficha ("€1.2 + IVA"), sin saber si son
  1,2 € o 1.200 €. El informe pinta "€2500 + IVA" (símbolo delante, sin separador de miles).

## 2. Diseño

### 2.1 Indicativo "Otro…" en visitas (fase A)

- Los dos formularios usan el macro `phone.phone_field("phone_", cc, local, required=True)`:
  mismo selector que compradores, opción "Otro…" con el indicativo escrito a mano (1 a 3 dígitos
  de E.164) y aviso en vivo si el número ya trae indicativo. Se carga `phone-field.js` y se
  elimina el script inline duplicado.
- Rutas `create_visit` / `update_visit`: `phone_from_form(country_code, number,
  other_code=country_code_other)`. Un indicativo escrito inválido o un número de menos de 6 /
  más de 12 dígitos devuelve al formulario con el mensaje de `PhoneValidationError`
  (hasta ahora no se validaba nada).
- Formato guardado: el mismo que compradores. Indicativo del selector → sin `+`
  (`34600112233`, igual que hoy); indicativo escrito → con `+` (`+41791234567`).
- Edición: `split_phone(visit.phone)` para que un teléfono guardado con `+41…` salga con
  "Otro…" y el 41 escrito.
- Dónde se muestra: tabla de visitas, vista previa y PDF pasan de `"+" + phone` a
  `phone_display` (`+34 600 112 233`, `+41 791 234 567`), que entiende los dos formatos. El envío
  por WhatsApp usa `canonical_phone` (solo dígitos, lo que pide la API).

### 2.2 Formato de los honorarios (fase B)

Regla única, la española: **la coma es el decimal y el punto solo separa miles**.

- Se admite: `2500`, `2.500`, `2500,50`, `2.500,50`, `2,5` (%), `1,2`.
- Se rechaza con mensaje: `1.2` ("Usa la coma para los decimales (1,2); el punto solo para los
  miles (2.500)"), más de dos decimales, un punto que no vaya seguido de tres dígitos.
- Se guarda normalizado, sin separador de miles y con coma si hay decimales: `2500`, `2500,5`,
  `2,5%`. Lo antiguo guardado con punto de miles (`2.500`) se lee como 2500.
- Se muestra en formato español con el símbolo detrás: `2.500 € + IVA`, `2.500,50 € + IVA`,
  `2,5 % + IVA`. Un valor antiguo que no se pueda interpretar se muestra tal cual + " + IVA".
- Formulario: `placeholder` "Ej: 2500" / "Ej: 2,5", pista bajo el campo con la regla,
  `pattern` HTML acorde y el mismo mensaje del servidor.
- Helpers nuevos en `app/core/numbers.py`: `parse_es_decimal(text) -> Decimal` y
  `format_es_decimal(value, max_decimals=2) -> str`, reutilizables.

## 3. Fases

- **Fase A — Indicativo "Otro…" en visitas.** Plantillas de alta y edición, `routes/visits.py`,
  `visits/table.html`, `visits/preview.html`, `visit_sheet_generator.py`, tests.
- **Fase B — Honorarios.** `app/core/numbers.py`, `models/property_visit.py`,
  `routes/visits.py`, los dos formularios, `tests/test_visit_purchase_fees.py`,
  `tests/test_numbers.py`.

## 4. Decisiones tomadas sin preguntar

1. El símbolo del euro pasa detrás del importe en la ficha (`2.500 € + IVA`), como se escribe en
   España; antes salía `€2500 + IVA`. Si se prefiere delante, es una línea en
   `purchase_fees_display`.
2. El teléfono del visitante pasa a validarse (6 a 12 dígitos locales), igual que el del comprador.
3. En el PDF y la vista previa el teléfono sale agrupado (`+34 600 112 233`) en vez de pegado.
