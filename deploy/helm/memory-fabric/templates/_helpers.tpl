{{- define "mf.name" -}}{{ .Release.Name }}-memory-fabric{{- end -}}
{{- define "mf.labels" -}}
app.kubernetes.io/name: memory-fabric
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "mf.tokenSecret" -}}{{ default (printf "%s-token" (include "mf.name" .)) .Values.dashboard.existingSecret }}{{- end -}}
