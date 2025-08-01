#  Copyright (c) 2018, The Monero Project
#  
#  All rights reserved.
#  
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#  
#  1. Redistributions of source code must retain the above copyright notice,
#  this list of conditions and the following disclaimer.
#  
#  2. Redistributions in binary form must reproduce the above copyright notice,
#  this list of conditions and the following disclaimer in the documentation
#  and/or other materials provided with the distribution.
#  
#  3. Neither the name of the copyright holder nor the names of its
#  contributors may be used to endorse or promote products derived from this
#  software without specific prior written permission.
#  
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.

TARGET = salvium-pool

TYPE = debug

ifeq ($(MAKECMDGOALS),release)
  TYPE = release
endif

ifeq ($(origin SALVIUM_BUILD_ROOT), undefined)
  SALVIUM_BUILD_ROOT = \
    ${SALVIUM_ROOT}/build/$(shell echo `uname | \
    sed -e 's|[:/\\ \(\)]|_|g'`/` \
    git -C ${SALVIUM_ROOT} branch | \
    grep '\* ' | cut -f2- -d' '| \
    sed -e 's|[:/\\ \(\)]|_|g'`)/release
endif

SALVIUM_INC = \
  ${SALVIUM_ROOT}/src \
  ${SALVIUM_ROOT}/external \
  ${SALVIUM_ROOT}/external/easylogging++ \
  ${SALVIUM_ROOT}/contrib/epee/include

SALVIUM_LIBS = \
  ${SALVIUM_BUILD_ROOT}/src/oracle/liboracle.a \
  ${SALVIUM_BUILD_ROOT}/src/serialization/libserialization.a \
  ${SALVIUM_BUILD_ROOT}/contrib/epee/src/libepee.a \
  ${SALVIUM_BUILD_ROOT}/src/cryptonote_basic/libcryptonote_basic.a \
  ${SALVIUM_BUILD_ROOT}/src/cryptonote_basic/libcryptonote_format_utils_basic.a \
  ${SALVIUM_BUILD_ROOT}/src/crypto/libcncrypto.a \
  ${SALVIUM_BUILD_ROOT}/src/common/libcommon.a \
  ${SALVIUM_BUILD_ROOT}/src/ringct/libringct_basic.a \
  ${SALVIUM_BUILD_ROOT}/src/device/libdevice.a \
  ${SALVIUM_BUILD_ROOT}/src/crypto/wallet/libwallet-crypto.a \
  ${SALVIUM_BUILD_ROOT}/external/easylogging++/libeasylogging.a \
  ${SALVIUM_BUILD_ROOT}/src/libversion.a \
  ${SALVIUM_BUILD_ROOT}/external/randomx/librandomx.a \
  ${SALVIUM_BUILD_ROOT}/src/cryptonote_core/libcryptonote_core.a \
  ${SALVIUM_BUILD_ROOT}/src/rpc/librpc_base.a 

DIRS = src data rxi/log/src

OS := $(shell uname -s)

CPPDEFS = _GNU_SOURCE AUTO_INITIALIZE_EASYLOGGINGPP LOG_USE_COLOR

W = -W -Wall -Wno-unused-parameter -Wuninitialized -Wno-attributes
OPT = -maes -fPIC
CFLAGS += $(W) -Wbad-function-cast $(OPT) -std=c99
CXXFLAGS += $(W) -Wno-reorder $(OPT) -std=c++17
LDPARAM += -fPIC -pie

ifeq ($(OS), Darwin)
  CXXFLAGS += -stdlib=libc++
  CPPDEFS += HAVE_MEMSET_S
  LDPARAM = 
endif

ifeq ($(TYPE),debug)
  CFLAGS += -g
  CXXFLAGS += -g
  CPPDEFS += DEBUG
endif

ifeq ($(TYPE), release)
  CFLAGS += -O3
  CXXFLAGS += -O3
endif

LDPARAM += $(LDFLAGS)

LIBS := 
#ifeq ($(OS), Darwin)
#  LIBS += c++ \
#	  boost_system-mt boost_date_time-mt boost_chrono-mt \
#	  boost_filesystem-mt boost_thread-mt boost_regex-mt \
#	  boost_serialization-mt boost_program_options-mt
#else
#  LIBS += dl uuid \
#	  boost_system boost_date_time boost_chrono \
#	  boost_filesystem boost_thread boost_regex \
#	  boost_serialization boost_program_options
#endif

HID_FOUND := $(shell grep -qo HIDAPI_LIBRARY-NOTFOUND \
  ${SALVIUM_BUILD_ROOT}/CMakeCache.txt; echo $$?)
ifeq ($(HID_FOUND), 1)
  LIBS += hidapi-libusb
endif

PKG_LIBS := 
#PKG_LIBS := $(shell pkg-config \
#  "libevent_core >= 2.1" \
#  "libevent_pthreads >= 2.1" \
#  "libevent_extra >= 2.1" \
#  json-c \
#  openssl \
#  libsodium \
#  --libs)

STATIC_LIBS = \
  -Wl,-Bstatic \
  -llmdb -lunbound -lnettle -lhogweed -lgmp \
  -luuid -lboost_system -lboost_date_time -lboost_chrono \
  -lboost_filesystem -lboost_thread -lboost_regex \
  -lboost_serialization -lboost_program_options \
  -levent_core -levent_pthreads -lrt \
  -levent -levent_extra -ljson-c -lssl -lcrypto -lsodium \
  -Wl,-Bdynamic \
  -lpthread -ldl

DLIBS =

INCPATH := $(DIRS) ${SALVIUM_INC} /opt/local/include /usr/local/include

PKG_INC := $(shell pkg-config \
  "libevent_core >= 2.1" \
  "libevent_pthreads >= 2.1" \
  "libevent_extra >= 2.1" \
  json-c \
  openssl \
  libsodium \
  --cflags)

LIBPATH := /opt/local/lib/ /usr/local/lib

CXX = g++
CC = gcc
XXD := $(shell command -v xxd 2> /dev/null)

STORE = build/$(TYPE)
SOURCE := $(foreach DIR,$(DIRS),$(wildcard $(DIR)/*.cpp))
CSOURCE := $(foreach DIR,$(DIRS),$(wildcard $(DIR)/*.c))
SSOURCE := $(foreach DIR,$(DIRS),$(wildcard $(DIR)/*.S))
HTMLSOURCE := $(foreach DIR,$(DIRS),$(wildcard $(DIR)/*.html))
HEADERS := $(foreach DIR,$(DIRS),$(wildcard $(DIR)/*.h))
OBJECTS := $(addprefix $(STORE)/, $(SOURCE:.cpp=.o))
COBJECTS := $(addprefix $(STORE)/, $(CSOURCE:.c=.o))
SOBJECTS := $(addprefix $(STORE)/, $(SSOURCE:.S=.o))
HTMLOBJECTS := $(addprefix $(STORE)/, $(HTMLSOURCE:.html=.o))
DFILES := $(addprefix $(STORE)/,$(SOURCE:.cpp=.d))
CDFILES := $(addprefix $(STORE)/,$(CSOURCE:.c=.d))
SDFILES := $(addprefix $(STORE)/,$(SSOURCE:.S=.d))


.PHONY: clean dirs debug release preflight

$(TARGET): preflight dirs $(OBJECTS) $(COBJECTS) $(SOBJECTS) $(HTMLOBJECTS)
	@echo Linking $(OBJECTS)...
	$(CXX) -o $(STORE)/$(TARGET) \
	  $(OBJECTS) $(COBJECTS) $(SOBJECTS) $(HTMLOBJECTS) \
	  $(LDPARAM) -Wl,--start-group $(SALVIUM_LIBS) -Wl,--end-group \
	  $(foreach LIBRARY, $(LIBS),-l$(LIBRARY)) \
	  $(foreach LIB,$(LIBPATH),-L$(LIB)) \
	  $(PKG_LIBS) $(STATIC_LIBS)
	@cp pool.conf $(STORE)/
	@cp tools/* $(STORE)/

$(STORE)/%.o: %.cpp
	@echo Creating object file for $*...
	$(CXX) -Wp,-MMD,$(STORE)/$*.dd $(CXXFLAGS) \
	  $(foreach INC,$(INCPATH),-I$(INC)) \
	  $(PKG_INC) \
	  $(foreach CPPDEF,$(CPPDEFS),-D$(CPPDEF)) \
	  -c $< -o $@
	@sed -e '1s/^\(.*\)$$/$(subst /,\/,$(dir $@))\1/' \
	  $(STORE)/$*.dd > $(STORE)/$*.d
	@rm -f $(STORE)/$*.dd

$(STORE)/%.o: %.c
	@echo Creating object file for $*...
	$(CC) -Wp,-MMD,$(STORE)/$*.dd $(CFLAGS) \
	  $(foreach INC,$(INCPATH),-I$(INC)) $(PKG_INC) \
	  $(foreach CPPDEF,$(CPPDEFS),-D$(CPPDEF)) -c $< -o $@
	@sed -e '1s/^\(.*\)$$/$(subst /,\/,$(dir $@))\1/' \
	  $(STORE)/$*.dd > $(STORE)/$*.d
	@rm -f $(STORE)/$*.dd

$(STORE)/%.o: %.S
	@echo Creating object file for $*...
	$(CC) -Wp,-MMD,$(STORE)/$*.dd $(CFLAGS) \
	  $(foreach INC,$(INCPATH),-I$(INC)) $(PKG_INC) \
	  $(foreach CPPDEF,$(CPPDEFS),-D$(CPPDEF)) -c $< -o $@
	@sed -e '1s/^\(.*\)$$/$(subst /,\/,$(dir $@))\1/' \
	  $(STORE)/$*.dd > $(STORE)/$*.d
	@rm -f $(STORE)/$*.dd

$(STORE)/%.o: %.html
	@echo Creating object file for $*...
	xxd -i $< | sed -e 's/src_//' -e 's/embed_//' > $(STORE)/$*.c
	$(CC) $(CFLAGS)  -c $(STORE)/$*.c -o $@
	@rm -f $(STORE)/$*.c

# Empty rule to prevent problems when a header is deleted.
%.h: ;

debug release : $(TARGET)

clean:
	@echo Making clean.
	@find ./build -type f -name '*.o' -delete
	@find ./build -type f -name '*.d' -delete
	@find ./build -type f -name $(TARGET) -delete

dirs:
	@-if [ ! -e $(STORE) ]; then mkdir -p $(STORE); fi;
	@-$(foreach DIR,$(DIRS), \
	  if [ ! -e $(STORE)/$(DIR) ]; then mkdir -p $(STORE)/$(DIR); fi; )

preflight:
ifeq ($(origin SALVIUM_ROOT), undefined)
  $(error You need to set an environment variable SALVIUM_ROOT \
    to your monero repository root)
endif
#ifndef PKG_LIBS
#  $(error Missing dependencies)
#endif
ifndef XXD
  $(error Command xxd not found)
endif

-include $(DFILES)
-include $(CDFILES)
-include $(SDFILES)

