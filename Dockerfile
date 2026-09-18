# syntax=docker/dockerfile:1

# RCH development/test image.
# Provides Ubuntu 24.04, Clang 20, GCC/G++ 13, CMake/Ninja, CGAL, and the
# Python environment needed by the repository scripts and CTest Python tests.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG LLVM_VERSION=20
ARG UBUNTU_CODENAME=noble

ENV VIRTUAL_ENV=/opt/rch-venv
ENV PATH="${VIRTUAL_ENV}/bin:/usr/lib/llvm-${LLVM_VERSION}/bin:${PATH}"
ENV CC=clang
ENV CXX=clang++
ENV PYTHON="${VIRTUAL_ENV}/bin/python"
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/apt.llvm.org.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/apt.llvm.org.gpg] https://apt.llvm.org/${UBUNTU_CODENAME}/ llvm-toolchain-${UBUNTU_CODENAME}-${LLVM_VERSION} main" \
    > /etc/apt/sources.list.d/llvm.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    clang-${LLVM_VERSION} \
    clang-format-${LLVM_VERSION} \
    clang-tidy-${LLVM_VERSION} \
    clangd-${LLVM_VERSION} \
    cmake \
    g++-13 \
    gcc-13 \
    gcovr \
    git \
    libboost-dev \
    libcgal-dev \
    libclang-rt-${LLVM_VERSION}-dev \
    libgmp-dev \
    libmpfr-dev \
    lld-${LLVM_VERSION} \
    llvm-${LLVM_VERSION} \
    make \
    ninja-build \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
    xz-utils \
    zlib1g-dev \
 && ln -sf /usr/bin/clang-${LLVM_VERSION} /usr/local/bin/clang \
 && ln -sf /usr/bin/clang++-${LLVM_VERSION} /usr/local/bin/clang++ \
 && ln -sf /usr/bin/clang-format-${LLVM_VERSION} /usr/local/bin/clang-format \
 && ln -sf /usr/bin/clang-tidy-${LLVM_VERSION} /usr/local/bin/clang-tidy \
 && ln -sf /usr/bin/clangd-${LLVM_VERSION} /usr/local/bin/clangd \
 && ln -sf /usr/bin/gcc-13 /usr/local/bin/gcc \
 && ln -sf /usr/bin/g++-13 /usr/local/bin/g++ \
 && ln -sf /usr/bin/lld-${LLVM_VERSION} /usr/local/bin/lld \
 && ln -sf /usr/bin/ld.lld-${LLVM_VERSION} /usr/local/bin/ld.lld \
 && ln -sf /usr/bin/llvm-ar-${LLVM_VERSION} /usr/local/bin/llvm-ar \
 && ln -sf /usr/bin/llvm-cov-${LLVM_VERSION} /usr/local/bin/llvm-cov \
 && ln -sf /usr/bin/llvm-profdata-${LLVM_VERSION} /usr/local/bin/llvm-profdata \
 && ln -sf /usr/bin/llvm-ranlib-${LLVM_VERSION} /usr/local/bin/llvm-ranlib \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work/rch

COPY requirements.txt /tmp/rch-requirements.txt

RUN python3 -m venv "${VIRTUAL_ENV}" \
 && "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel \
 && "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir -r /tmp/rch-requirements.txt

COPY . .

CMD ["/bin/bash"]
