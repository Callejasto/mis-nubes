# Traducir Mis nubes · Translating My Clouds

**Español.** El programa está escrito en español. Cada idioma es un archivo `idiomas/<código>.json`
con pares «texto en español» → «texto traducido».

1. Crea la plantilla de tu idioma (por ejemplo, francés):
   `python3 src/mis_nubes.py --exportar-idioma fr > idiomas/fr.json`
   (o copia `en.json` y úsalo como guía).
2. Traduce **solo los valores** (a la derecha). No cambies las claves (a la izquierda).
3. Respeta las `{variables}`, las etiquetas como `<b>…</b>` y los saltos `\n`.
4. Pruébalo: copia el archivo a `~/.local/share/mis-nubes/idiomas/` y elige el idioma en
   **ⓘ › Idioma**. Los textos sin traducir se muestran en español.
5. Envía tu archivo con un *pull request*. ¡Gracias!

**English.** The program is written in Spanish. Each language is a file `idiomas/<code>.json`
mapping "Spanish text" → "translated text".

1. Create a template for your language (for example, French):
   `python3 src/mis_nubes.py --exportar-idioma fr > idiomas/fr.json`
   (or copy `en.json` and use it as a guide).
2. Translate **only the values** (right side). Do not change the keys (left side).
3. Keep the `{variables}`, tags like `<b>…</b>` and `\n` line breaks.
4. Test it: copy the file to `~/.local/share/mis-nubes/idiomas/` and choose the language in
   **ⓘ › Language**. Untranslated texts are shown in Spanish.
5. Send your file in a pull request. Thank you!
