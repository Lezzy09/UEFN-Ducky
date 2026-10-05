# Pièces jointes vidéo — v2 (retours de relecture)

Date : 2026-10-06 — validé par l'utilisateur. Complète `2026-10-05-video-attachments-design.md` (qui reste la référence pour tout ce qui n'est pas modifié ici).

Retours traités : préparation en arrière-plan dès le dépôt, limites d'images lues depuis le fournisseur du modèle, ffmpeg livré avec l'app, transcription audio.

## 1. Préparation en arrière-plan dès le dépôt

- `stage_video_attachment` démarre aussitôt une tâche de fond (`backend/agent/video/prep.py`) si le destinataire a besoin d'images (règle `needs_frames` existante ; groupe ou chat inconnu → oui).
- La tâche extrait les N images à côté du fichier en attente (`<staged_id>.fNN-KK.jpg`, même convention que `frames.frame_paths`) puis, si besoin, la transcription (§4) dans `<staged_id>.transcript.txt`.
- Nouvelle API `get_video_prep_status(staged_ids)` → par id : `{state: "queued"|"extracting"|"transcribing"|"ready"|"error", frames_done, frames_total, transcript: "ok"|"none"|"skipped", transcript_note, error}`.
- La pastille affiche « Extracting frames 7/20 », « Transcribing audio… », « Ready » (+ note de transcription), ou l'erreur avec Retry. L'envoi reste bloqué tant que la préparation n'est pas « ready ».
- À l'envoi, `persist_message_attachments` copie aussi les fichiers frères (images + transcription) en les renommant avec le nom persistant ; `extract_frames` trouve alors le cache et ne refait rien. Si la préparation n'a pas tourné (provider changé, etc.), le chemin d'envoi existant extrait comme avant.

## 2. Limites selon le modèle (lues chez le fournisseur)

- `ModelInfo` (host, `backend/agent/model_fetch.py`) gagne `max_images: int | None`, `supports_video: bool | None`, `supports_audio: bool | None`.
- Les plugins fournisseurs les remplissent quand leur API les expose (PR séparée par plugin) ; sinon `None`.
- `limits.media_limits_for(provider, model) -> VideoLimits` : `max_images_per_request` = `ModelInfo.max_images` → sinon table par fournisseur (`anthropic` 100, `openai` 500, `gemini` 3000, autres 20).
- Réglages : `video_frames_per_video` et `max_images_per_message` acceptent **0 = Auto** (nouveau défaut). Auto : images par message = max du modèle ; images par vidéo = min(20, max du modèle). Une valeur > 0 force le réglage manuel (bornes inchangées).
- `budget.apply_media_budget` utilise le max du modèle au lieu de 100 fixe.
- Gemini : vidéo native seulement si `supports_video` n'est pas `False`.

## 3. ffmpeg livré avec l'app

- `build/fetch_ffmpeg.py` télécharge l'archive épinglée au build (constantes de `ffmpeg_install`), vérifie le SHA-256, extrait `ffmpeg.exe`, `ffprobe.exe`, les DLL et `LICENSE.txt` dans `build/ffmpeg-bundle/` (ignoré par git, réutilisé si déjà présent et marqué).
- `unified.spec` les embarque sous `tools/ffmpeg/`.
- `ffmpeg_install.binaries()` cherche d'abord le dossier embarqué (`packaged_data_root()/tools/ffmpeg`), puis AppData. `status()` renvoie `bundled: true` ; `remove()` ne supprime jamais l'embarqué.
- Le téléchargement automatique reste uniquement pour les exécutions depuis le code source.
- Paramètres → Videos : « Included with UEFN-Ducky (version) », sans boutons Install/Remove quand embarqué.
- `THIRD_PARTY_NOTICES.md` : FFmpeg passe en « Bundled » (LGPL, LICENSE.txt livré à côté).

## 4. Audio : MP3 puis transcription

- `backend/agent/video/audio.py` : `has_audio(ffprobe, video)`, `extract_mp3(ffmpeg, video, out)` (mono, 16 kHz, 48 kb/s), `transcribe_video(video) -> TranscriptResult(text, note)`.
- Transcription via la fonction existante `backend.voice.transcription.transcribe_audio(b64, "audio/mpeg")` (clé OpenAI). Pas de clé / gateway OpenAI absent / MP3 > 24 Mo / pas de piste audio → pas de texte, note lisible (« No transcript — needs an OpenAI key », « No audio track », « Audio too long to transcribe »). Jamais bloquant.
- Seulement quand le destinataire reçoit des images (Gemini natif entend déjà le son).
- La ligne stockée de la vidéo gagne `transcript` (texte) et `transcript_note`. `MessageAttachment.transcript`.
- Constructeurs (Anthropic / OpenAI / Gemini-images) : bloc texte `Transcript of video "<name>":\n<texte>` avant les images. Agents de code : ajouté au texte du message avec les chemins.
- Envoi et rattrapage d'historique : si une vidéo a des images mais pas de tentative de transcription, la transcription est tentée (meilleur effort, statut poussé).

## Hors périmètre

Fichiers audio seuls (mp3/wav joints directement), horodatage par segment dans la transcription, transcription locale hors ligne.
