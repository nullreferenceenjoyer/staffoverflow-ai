#!/bin/sh
# Раз в сутки снимает дамп базы и удаляет старые. Запускается сервисом backup.
set -u

while true; do
    file="/backups/hr_edu_$(date +%Y%m%d_%H%M%S).dump"
    if pg_dump --format=custom --file="$file"; then
        echo "backup: создан $file"
        find /backups -name 'hr_edu_*.dump' -mtime "+${BACKUP_KEEP_DAYS:-14}" -delete
    else
        echo "backup: не удалось снять дамп" >&2
        rm -f "$file"
    fi
    sleep 86400
done
