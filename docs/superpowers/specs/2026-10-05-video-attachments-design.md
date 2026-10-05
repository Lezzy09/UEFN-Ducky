# Pièces jointes vidéo dans le chat — design

Date : 2026-10-05
Statut : validé en discussion, en attente de relecture

## Objectif

Permettre de joindre une vidéo à un message (prompt) pour mieux expliquer un problème,
un comportement ou une référence visuelle. Chaque modèle reçoit la vidéo sous la forme
qu'il comprend :

- **Gemini** reçoit la vidéo d'origine (natif, pas de ffmpeg).
- **Claude, OpenAI, Ollama, Kimi, SpaceX AI** reçoivent des images extraites par ffmpeg.
- **Agents de code (Claude Code, Codex, Cursor)** reçoivent les chemins des images extraites.

Le choix est automatique, selon le modèle du Ducky destinataire. L'utilisateur ne choisit rien.

## Hors périmètre (v1)

- Audio / transcription (prévu plus tard).
- Gemini File API pour les vidéos de plus de ~20 Mo (repli sur les images extraites).
- Hébergement de ffmpeg sur nos serveurs (GitHub BtbN pour l'instant).
- Détection de changement de scène (images réparties régulièrement uniquement).
- Transfert de vidéos de plus de 200 Mo (demanderait de ne plus passer par base64).

## Point d'entrée unique

Tous les plugins fournisseurs appellent `backend/agent/multimodal_content.py`
(`build_anthropic_user_content`, `build_openai_user_content`, `build_gemini_user_parts`).
Le support vidéo s'ajoute là : **aucun plugin n'est modifié**.
Les agents de code passent par `collect_image_paths` (`backend/agent/coding_agents/runner.py`).

## Ajustements après lecture du code (2026-10-05)

- **Envoi anticipé (staging)** : la vidéo est envoyée au backend **une seule fois, dès
  l'ajout** (`stage_video_attachment`), dans `%LOCALAPPDATA%\UEFN-Ducky\video_staging\`.
  La zone de saisie, la file d'attente et le cache du brouillon ne gardent qu'une
  référence (`staged_id`), jamais 100 Mo de base64. Les fichiers en attente de plus de
  24 h sont supprimés.
- **Groupes** : chaque membre reçoit les pièces jointes brutes et passe par son propre
  envoi (`group_orchestrator.py`). Le choix vidéo native / images se fait donc
  naturellement par membre. Au moment de l'ajout, un groupe déclenche toujours le
  téléchargement de ffmpeg (simplification).
- **Gemini** : types acceptés en natif : MP4, WebM, MOV (`video/mov`). Le MKV passe par
  les images.
- **Historique** : comme les images aujourd'hui, les vidéos des messages précédents sont
  renvoyées au modèle à chaque tour (vidéo native pour Gemini, images sinon).
- **Textes de l'interface en anglais**, comme le reste de l'app.
- **ffmpeg épinglé** : `autobuild-2026-08-31-13-27` (les builds de fin de mois restent
  disponibles environ 2 ans chez BtbN), archive
  `ffmpeg-n9.0.1-11-ge47273f4d9-win64-lgpl-shared-9.0.zip` (67,2 Mo), SHA-256
  `83a824f0729a69d143c9865125bb86988a11dd388325f0033711045522068aa0`, vérifié.
- La route `/chat-attachments/` ne gère pas encore les requêtes `Range` (seule la route
  des médias du projet le fait) : à ajouter.

## 1. Modèle de données et flux

### Type de pièce jointe

`MessageAttachment.kind` accepte `"video"` en plus de `"image"` et `"file"`.
Une vidéo porte : `name`, `mime`, `path` (relatif au dossier de la conversation),
`duration_s`, `size_bytes`, et la liste de ses images extraites
(`frames: [{path, t_s}]`) une fois l'extraction faite.

Formats acceptés : MP4, WebM, MOV, MKV (`video/mp4`, `video/webm`,
`video/quicktime`, `video/x-matroska`).

### Flux

1. **Ajout** dans la zone de saisie (glisser-déposer, coller, trombone), comme une image.
2. **Stockage** : la vidéo d'origine est écrite dans
   `conversations/<id>/attachments/` (comme les images, `persist_message_attachments`).
3. **Extraction** : si nécessaire (voir §2), ffmpeg extrait N images réparties
   régulièrement sur la durée, redimensionnées à 1280 px de large maximum, en JPEG,
   écrites à côté de la vidéo (`<horodatage>_<i>_<nom>.frame-<k>.jpg`). Le résultat est
   mis en cache : une relance du message ou un groupe réutilise les mêmes images.
4. **Envoi** dans `multimodal_content.py` :
   - Gemini et vidéo ≤ 20 Mo : vidéo d'origine en `Part.from_bytes(mime_type=video/…)`.
   - Gemini et vidéo > 20 Mo : images extraites (comme les autres modèles).
   - Anthropic / OpenAI (et compatibles) : un bloc texte de repère avant chaque image,
     ex. `Vidéo "bug.mp4" — image 3/20 à 00:12`, puis l'image.
   - Agents de code : chemins absolus des images extraites ajoutés aux `image_paths`,
     plus une ligne `Video file: <chemin>` dans le texte.
5. **Groupes** : la vidéo d'origine est toujours conservée ; la conversion se fait par
   destinataire au moment de l'envoi. Un groupe mixte (Gemini + Claude) fonctionne.

### Pas de réhydratation base64 des vidéos

`hydrate_attachment_dict` réencode aujourd'hui chaque image en base64 à chaque
rechargement. **Les vidéos sont exclues de ce mécanisme** : l'interface les lit via la
route locale existante `/chat-attachments/<conv>/<fichier>` (`build_chat_attachment_url`),
et le backend les lit depuis le disque au moment de l'envoi.
`_CHAT_FILE_RE` est étendu à `mp4|webm|mov|mkv`.

### Paramètres (réglables)

Nouveaux champs de `PanelSettings` (`frontend/settings.py`) avec leur entrée
`FIELD_META` (`frontend/settings_schema.py`, onglet « Vidéos », `settable=True`) :

| Champ | Défaut | Plage |
|---|---|---|
| `video_max_mb` | 100 | 10–200 |
| `video_frames_per_video` | 20 | 1–40 |
| `max_images_per_message` | 40 | 1–100 |

`max_images_per_message` remplace la constante `_MAX_IMAGES = 20` côté backend
(`attachments.py`) et `MAX_IMAGES` côté interface (`useComposerAttachments.ts`).
Les images extraites des vidéos comptent dans ce total. Les valeurs hors plage sont
ramenées dans la plage (clamp) à la lecture.

## 2. ffmpeg téléchargé automatiquement

### Emplacement

`%LOCALAPPDATA%\UEFN-Ducky\tools\ffmpeg\<version>\` (via `resolve_app_data_dir`),
contenant seulement `ffmpeg.exe` et `ffprobe.exe`.

### Source

Build **LGPL** win64 de BtbN/FFmpeg-Builds sur GitHub, **version autobuild datée
épinglée** (jamais `latest`). L'URL, la version et le **SHA-256 de l'archive** sont des
constantes dans un seul module (`backend/agent/video/ffmpeg_install.py`). Changer de
version = modifier ces constantes.

Licence : LGPL uniquement (pas de build GPL), ffmpeg appelé comme processus séparé,
mention ajoutée dans `THIRD_PARTY_NOTICES.md`, et `scripts/check_licenses.py` mis à jour
si nécessaire.

### Quand télécharger

Uniquement si une extraction est nécessaire : une vidéo est ajoutée **et** (au moins un
destinataire n'est pas Gemini **ou** la vidéo dépasse 20 Mo). Un utilisateur
Gemini-only avec de petites vidéos ne télécharge jamais ffmpeg.

Le téléchargement de ffmpeg démarre dès l'ajout de la vidéo (la pastille affiche la
progression) ; l'envoi attend que ffmpeg soit prêt. L'extraction des images, elle, se
fait au moment de l'envoi (§1, étape 3), avec l'état « Extraction des images… » sur le
message.

### Sécurité

- Téléchargement dans un fichier `.part`, vérification SHA-256, puis extraction et
  renommage atomique. Un fichier qui ne correspond pas est supprimé et **jamais exécuté**.
- Un seul téléchargement à la fois (verrou), quel que soit le nombre de vidéos ajoutées.
- Si l'URL épinglée renvoie 404 : message « Téléchargement impossible, mets l'app à jour ».

### Paramètres → Vidéos

Affiche l'état : « Installé (version X) » / « Non installé », avec
**[Installer maintenant]** et **[Supprimer]**.

### Erreurs

Règle : un message n'est jamais envoyé en retirant silencieusement une vidéo.

| Cas | Comportement |
|---|---|
| Pas d'internet / échec du téléchargement | Erreur sur la pastille + **[Réessayer]** |
| SHA-256 incorrect | « Téléchargement corrompu », fichier supprimé, **[Réessayer]** |
| URL épinglée disparue (404) | « Téléchargement impossible, mets l'app à jour » |
| Vidéo illisible / corrompue | « Impossible de lire cette vidéo » |
| Vidéo trop lourde | Message avec la limite réglée |
| Trop d'images au total | Message avec la limite réglée |
| Modèle sans vision | Même erreur que pour les images aujourd'hui |
| Extraction > 60 s | Arrêt du processus ffmpeg + erreur |

## 3. Interface

### Zone de saisie

- `useComposerAttachments.ts` : nouveau `kind: "video"`, limites lues depuis les
  paramètres au lieu des constantes.
- Pastille vidéo : miniature (première image), durée, taille, état
  (« Préparation… 42 % » / « Prête » / erreur + **[Réessayer]**).
- Clic : `AttachmentPreviewModal.tsx` affiche un lecteur `<video>`.

### Historique

- `ChatPane.tsx` : rendu d'un lecteur `<video controls>` pointant sur l'URL
  `/chat-attachments/...` (pas de data URL).
- Ligne repliable « 20 images envoyées à l'IA » qui montre les images extraites avec
  leurs repères de temps.

### À vérifier pendant l'implémentation

La route `/chat-attachments/` doit gérer les requêtes HTTP `Range` pour que l'avance
rapide fonctionne dans `<video>`. Sinon, l'ajouter.

## 4. Organisation du code

Nouveau paquet `backend/agent/video/` :

- `ffmpeg_install.py` — constantes de version/URL/SHA-256, téléchargement, vérification,
  état, suppression.
- `frames.py` — `probe_duration`, `extract_frames(video_path, n, max_width, timeout_s)`,
  cache des images à côté de la vidéo.
- `routing.py` — décide « vidéo native » ou « images » selon le fournisseur et la taille.

Modifiés : `message_attachment.py`, `attachments.py`, `multimodal_content.py`,
`coding_agents/runner.py` (`collect_image_paths`), `frontend/ui_web/conversation_attachments.py`,
`frontend/settings.py`, `frontend/settings_schema.py`, `build_chat_attachment_url`/route,
`useComposerAttachments.ts`, `types/panel.ts`, `ChatPane.tsx`,
`AttachmentPreviewModal.tsx`, page Paramètres, `THIRD_PARTY_NOTICES.md`.

## 5. Tests

Backend (pytest) :

- Analyse d'une pièce jointe vidéo : mime, taille max réglable, formats refusés.
- Routage : Gemini ≤ 20 Mo → vidéo native ; Gemini > 20 Mo → images ; Anthropic/OpenAI
  → images avec bloc texte de repère avant chaque image.
- Limite `max_images_per_message` incluant les images extraites.
- Agents de code : les images extraites apparaissent dans `collect_image_paths`.
- Les vidéos ne sont pas réencodées en base64 par `hydrate_attachment_dict`.
- `ffmpeg_install` : SHA-256 correct, SHA-256 incorrect (fichier supprimé, jamais lancé),
  `.part` jamais exécuté, 404, verrou (un seul téléchargement).
- `frames` : délai de 60 s dépassé → processus tué ; vidéo illisible → erreur claire.
- Intégration réelle (ignorée si ffmpeg absent) : génère une vidéo de 3 s avec ffmpeg,
  extrait N images, vérifie le nombre et les repères de temps.
- `test_settings_schema.py` passe avec les nouveaux champs.

Interface (vitest) :

- `useComposerAttachments.test.ts` : ajout d'une vidéo, limite de taille, limite d'images
  issue des paramètres.
