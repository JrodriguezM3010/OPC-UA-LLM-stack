# Docker Hub org/user
DOCKERHUB_NAMESPACE ?= juanotee

IMAGE_VERSION       ?= $(shell cat VERSION)
PLATFORMS           ?= linux/amd64,linux/arm64

# Multi-arch builds need the docker-container driver; the default builder
# cannot emit a manifest list. Created by `make buildx-setup`.
BUILDER             ?= multiarch

GATEWAY_REPO        := $(DOCKERHUB_NAMESPACE)/tank-ai-gateway
DB_REPO             := $(DOCKERHUB_NAMESPACE)/tank-ai-db
N8N_REPO            := $(DOCKERHUB_NAMESPACE)/tank-ai-n8n
CHATUI_REPO         := $(DOCKERHUB_NAMESPACE)/tank-ai-chatui
OLLAMA_REPO         := $(DOCKERHUB_NAMESPACE)/tank-ai-ollama

LABEL               := --label org.opencontainers.image.version=$(IMAGE_VERSION)

define buildx_push
	docker buildx build \
		--builder $(BUILDER) \
		--platform $(PLATFORMS) \
		-f $(1) \
		-t $(2):$(IMAGE_VERSION) \
		-t $(2):latest \
		$(LABEL) \
		--push \
		.
endef

# --- one-time builder setup ------------------------------------
.PHONY: buildx-setup
buildx-setup:
	docker buildx inspect $(BUILDER) >/dev/null 2>&1 || \
		docker buildx create --name $(BUILDER) --driver docker-container \
			--driver-opt network=host --bootstrap

# --- multi-arch build & push -----------------------------------
.PHONY: push-gateway
push-gateway: buildx-setup
	$(call buildx_push,Dockerfile.gateway,$(GATEWAY_REPO))

.PHONY: push-db
push-db: buildx-setup
	$(call buildx_push,Dockerfile.db,$(DB_REPO))

.PHONY: push-n8n
push-n8n: buildx-setup
	$(call buildx_push,Dockerfile.n8n,$(N8N_REPO))

.PHONY: push-chatui
push-chatui: buildx-setup
	$(call buildx_push,Dockerfile.chatui,$(CHATUI_REPO))

.PHONY: push-ollama
push-ollama: buildx-setup
	$(call buildx_push,Dockerfile.ollama,$(OLLAMA_REPO))

# Build single-arch for your host and load into local docker (no push)
.PHONY: docker-build-local
docker-build-local:
	docker buildx build --load -f Dockerfile.gateway -t $(GATEWAY_REPO):dev .
	docker buildx build --load -f Dockerfile.db      -t $(DB_REPO):dev .
	docker buildx build --load -f Dockerfile.n8n     -t $(N8N_REPO):dev .
	docker buildx build --load -f Dockerfile.chatui  -t $(CHATUI_REPO):dev .
	docker buildx build --load -f Dockerfile.ollama  -t $(OLLAMA_REPO):dev .

# The deploy file pins exact tags, so it must be bumped with the version.
# Cheaper to fail here than to let someone deploy a stale tag.
DEPLOY_FILE         ?= deploy/compose.yaml

.PHONY: check-deploy-tag
check-deploy-tag:
	@if [ ! -f $(DEPLOY_FILE) ]; then \
		echo "$(DEPLOY_FILE) not found - skipping tag check"; \
	elif ! grep -q "tank-ai-gateway:$(IMAGE_VERSION)" $(DEPLOY_FILE); then \
		echo "$(DEPLOY_FILE) does not reference version $(IMAGE_VERSION):"; \
		grep -n "image:" $(DEPLOY_FILE); \
		echo "bump it, or set IMAGE_VERSION to match."; exit 1; \
	else \
		echo "$(DEPLOY_FILE) pins $(IMAGE_VERSION)"; \
	fi

# All five images share IMAGE_VERSION, so a release pushes them together —
# one version is one known-good set.
.PHONY: push
push: check-deploy-tag push-gateway push-db push-n8n push-chatui push-ollama
