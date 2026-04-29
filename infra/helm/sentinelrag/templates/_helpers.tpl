{{/*
SentinelRAG shared template helpers.

The convention is: every workload template calls these helpers with a "ctx"
dict so the same helpers render the api / temporal-worker / frontend without
copy-paste.

Example call site:
    {{- $ctx := dict "Values" .Values "Release" .Release "Chart" .Chart "workload" "api" -}}
    {{ include "sentinelrag.fullname" $ctx }}
*/}}

{{/* ---- Names ---- */}}

{{- define "sentinelrag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
sentinelrag.fullname computes "<release>-<chart>" or honors fullnameOverride.
*/}}
{{- define "sentinelrag.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Workload-scoped fullname: "<release>-<chart>-<workload>"
ctx must include .workload (string).
*/}}
{{- define "sentinelrag.workload.fullname" -}}
{{- $base := include "sentinelrag.fullname" . -}}
{{- printf "%s-%s" $base .workload | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* ---- Labels ---- */}}

{{- define "sentinelrag.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "sentinelrag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sentinelrag
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Workload-scoped labels (adds app.kubernetes.io/component).
*/}}
{{- define "sentinelrag.workload.labels" -}}
{{ include "sentinelrag.labels" . }}
app.kubernetes.io/component: {{ .workload }}
{{- end -}}

{{/*
Selector labels are stable across versions — never include chart version or
appVersion. These end up baked into Deployment.spec.selector.matchLabels and
must not change after first apply.
*/}}
{{- define "sentinelrag.workload.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sentinelrag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .workload }}
{{- end -}}

{{/* ---- Service account name ---- */}}

{{- define "sentinelrag.workload.serviceAccountName" -}}
{{- $w := index .Values .workloadKey -}}
{{- if and $w.serviceAccount $w.serviceAccount.create -}}
{{- default (include "sentinelrag.workload.fullname" .) $w.serviceAccount.name -}}
{{- else -}}
{{- default "default" (and $w.serviceAccount $w.serviceAccount.name) -}}
{{- end -}}
{{- end -}}

{{/* ---- Image reference ---- */}}

{{/*
Resolve image as "<registry>/<workload-image-name>:<tag>".
Tag precedence: workload.image.tag > .Values.image.tag.
*/}}
{{- define "sentinelrag.workload.image" -}}
{{- $w := index .Values .workloadKey -}}
{{- $registry := .Values.image.registry -}}
{{- $name := $w.image.name -}}
{{- $tag := default .Values.image.tag $w.image.tag -}}
{{- printf "%s/%s:%s" $registry $name $tag -}}
{{- end -}}

{{/* ---- Env composition ----

We render envFrom as a list of configMapRef + secretRef entries, plus an
inline env list for sharedEnv overrides and per-workload env scalars.

Helper consumers pass:
    workload     — display name ("api" / "temporal-worker" / "frontend")
    workloadKey  — the values key ("api" / "temporalWorker" / "frontend")
*/}}

{{- define "sentinelrag.workload.envFrom" -}}
{{- $w := index .Values .workloadKey -}}
- configMapRef:
    name: {{ include "sentinelrag.workload.fullname" . }}-config
{{- if and $w.envFromSecret $w.envFromSecret.name }}
- secretRef:
    name: {{ $w.envFromSecret.name }}
{{- end }}
{{- end -}}

{{/*
Inline env list: shared env merged with per-workload `env`. Workload values
win on key collision. Both are flat string maps.
*/}}
{{- define "sentinelrag.workload.env" -}}
{{- $w := index .Values .workloadKey -}}
{{- $merged := merge (dict) (default (dict) $w.env) (default (dict) .Values.sharedEnv) -}}
{{- range $k, $v := $merged }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}

{{/* ---- Cloud switch ---- */}}

{{/*
Default IngressClass per cloud, used when an Ingress block leaves
className unset.
*/}}
{{- define "sentinelrag.defaultIngressClass" -}}
{{- $cloud := default "local" .Values.cloud -}}
{{- if eq $cloud "aws" -}}alb
{{- else if eq $cloud "gcp" -}}gce
{{- else if eq $cloud "azure" -}}azure-application-gateway
{{- else -}}nginx
{{- end -}}
{{- end -}}

{{/*
Resolve the actual IngressClass for a workload's ingress block. Values shape:
    workload.ingress.className
Returns the explicit value when set, else the cloud default.
*/}}
{{- define "sentinelrag.workload.ingressClass" -}}
{{- $w := index .Values .workloadKey -}}
{{- if and $w.ingress $w.ingress.className }}
{{- $w.ingress.className -}}
{{- else }}
{{- include "sentinelrag.defaultIngressClass" . -}}
{{- end }}
{{- end -}}

{{/* ---- Pod / container security context ---- */}}

{{- define "sentinelrag.podSecurityContext" -}}
{{- with .Values.podSecurityContext }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "sentinelrag.containerSecurityContext" -}}
{{- with .Values.containerSecurityContext }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* ---- Probes (HTTP) ----
Renders liveness + readiness probes for HTTP workloads (api, frontend).
*/}}
{{- define "sentinelrag.workload.httpProbes" -}}
{{- $w := index .Values .workloadKey -}}
livenessProbe:
  httpGet:
    path: {{ $w.healthCheck.path }}
    port: http
  initialDelaySeconds: {{ $w.healthCheck.livenessInitialDelaySeconds }}
  periodSeconds: {{ $w.healthCheck.periodSeconds }}
  timeoutSeconds: {{ $w.healthCheck.timeoutSeconds }}
  failureThreshold: {{ $w.healthCheck.failureThreshold }}
readinessProbe:
  httpGet:
    path: {{ $w.healthCheck.path }}
    port: http
  initialDelaySeconds: {{ $w.healthCheck.readinessInitialDelaySeconds }}
  periodSeconds: {{ $w.healthCheck.periodSeconds }}
  timeoutSeconds: {{ $w.healthCheck.timeoutSeconds }}
  failureThreshold: {{ $w.healthCheck.failureThreshold }}
{{- end -}}

{{/* ---- imagePullSecrets ---- */}}
{{- define "sentinelrag.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}
