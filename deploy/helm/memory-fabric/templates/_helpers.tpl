{{- define "memory-fabric.name" -}}{{ .Release.Name }}-memory-fabric{{- end -}}
{{- define "memory-fabric.labels" -}}
app.kubernetes.io/name: memory-fabric
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "memory-fabric.tokenSecret" -}}{{ default (printf "%s-token" (include "memory-fabric.name" .)) .Values.dashboard.existingSecret }}{{- end -}}
