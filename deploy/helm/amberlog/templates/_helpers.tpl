{{- define "amberlog.name" -}}{{ .Release.Name }}-amberlog{{- end -}}
{{- define "amberlog.labels" -}}
app.kubernetes.io/name: amberlog
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "amberlog.tokenSecret" -}}{{ default (printf "%s-token" (include "amberlog.name" .)) .Values.dashboard.existingSecret }}{{- end -}}
