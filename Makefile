PLUGIN_NAME=		arpwatch
PLUGIN_VERSION=		1.0
PLUGIN_COMMENT=		Get notified when a new MAC address appears on the network
PLUGIN_MAINTAINER=	wrcrooks
PLUGIN_WWW=		https://github.com/wrcrooks/ARPWatch
# scripts only, the package installs on any architecture and FreeBSD version
PLUGIN_NO_ABI=		yes

.include "../../Mk/plugins.mk"
