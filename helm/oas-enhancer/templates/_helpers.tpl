{{/*
Expand the name of the chart.
*/}}
{{- define "oas-enhancer.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "oas-enhancer.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "oas-enhancer.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend selector labels
*/}}
{{- define "oas-enhancer.backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "oas-enhancer.fullname" . }}-backend
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
UI selector labels
*/}}
{{- define "oas-enhancer.ui.selectorLabels" -}}
app.kubernetes.io/name: {{ include "oas-enhancer.fullname" . }}-ui
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend image
*/}}
{{- define "oas-enhancer.backend.image" -}}
{{- if .Values.registry -}}
{{ .Values.registry }}/{{ .Values.backend.image }}:{{ .Values.backend.tag }}
{{- else -}}
{{ .Values.backend.image }}:{{ .Values.backend.tag }}
{{- end }}
{{- end }}

{{/*
UI image
*/}}
{{- define "oas-enhancer.ui.image" -}}
{{- if .Values.registry -}}
{{ .Values.registry }}/{{ .Values.ui.image }}:{{ .Values.ui.tag }}
{{- else -}}
{{ .Values.ui.image }}:{{ .Values.ui.tag }}
{{- end }}
{{- end }}

{{/*
Name of the secret holding OPENAI_API_KEY
*/}}
{{- define "oas-enhancer.secretName" -}}
{{- if .Values.backend.existingSecret -}}
{{ .Values.backend.existingSecret }}
{{- else -}}
{{ include "oas-enhancer.fullname" . }}-backend-secret
{{- end }}
{{- end }}
