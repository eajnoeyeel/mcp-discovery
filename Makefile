ROOT := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
SRC := $(ROOT)/src
LAMBDAS := $(ROOT)/service/lambdas
MLP := $(ROOT)/service

define copy_common
	cp $(SRC)/models.py $(1)/
	cp $(SRC)/config.py $(1)/
endef

define copy_pipeline
	$(call copy_common,$(1))
	cp -r $(SRC)/pipeline $(1)/
	cp -r $(SRC)/embedding $(1)/
	cp -r $(SRC)/retrieval $(1)/
	cp -r $(SRC)/reranking $(1)/
endef

define copy_retrieval
	$(call copy_common,$(1))
	cp -r $(SRC)/embedding $(1)/
	cp -r $(SRC)/retrieval $(1)/
endef

define copy_mlp_runtime
	mkdir -p $(1)/service && \
	cp $(MLP)/__init__.py $(1)/service/ && \
	cp -r $(MLP)/adapters $(1)/service/ && \
	cp -r $(MLP)/analytics $(1)/service/ && \
	cp -r $(MLP)/lambdas $(1)/service/ && \
	cp -r $(MLP)/rag $(1)/service/ && \
	cp -r $(MLP)/services $(1)/service/ && \
	cp -r $(MLP)/shared $(1)/service/ && \
	cp -r $(MLP)/validation $(1)/service/
endef

define pip_install
	pip3 install -r $(1)/requirements.txt -t $(1)/ --quiet
endef

define clean_pycache
	find $(1) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
endef

.PHONY: build-ApiKeyAuthorizerFunction
build-ApiKeyAuthorizerFunction:
	cp $(LAMBDAS)/authorizer/handler.py $(ARTIFACTS_DIR)/

.PHONY: build-RegisterFunction
build-RegisterFunction:
	cp $(LAMBDAS)/register/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/register/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_common,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-ExecuteFunction
build-ExecuteFunction:
	cp $(LAMBDAS)/execute/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/execute/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_common,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-IndexFunction
build-IndexFunction:
	cp $(LAMBDAS)/index/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/index/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_retrieval,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-SearchFunction
build-SearchFunction:
	cp $(LAMBDAS)/search/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/search/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_pipeline,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-CatalogFunction
build-CatalogFunction:
	cp $(LAMBDAS)/catalog/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/catalog/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_common,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-DashboardFunction
build-DashboardFunction:
	cp $(LAMBDAS)/dashboard/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/dashboard/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_common,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))

.PHONY: build-BridgeFunction
build-BridgeFunction:
	cp $(LAMBDAS)/bridge/handler.py $(ARTIFACTS_DIR)/
	cp $(LAMBDAS)/bridge/requirements.txt $(ARTIFACTS_DIR)/
	$(call copy_pipeline,$(ARTIFACTS_DIR))
	$(call copy_mlp_runtime,$(ARTIFACTS_DIR))
	$(call pip_install,$(ARTIFACTS_DIR))
	$(call clean_pycache,$(ARTIFACTS_DIR))
