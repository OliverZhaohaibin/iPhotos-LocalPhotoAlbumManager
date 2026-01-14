import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."  // Import local QML files

Rectangle {
    id: sidebar
    color: "#eef3f6"
    
    // Color constants matching the widget implementation
    readonly property color backgroundColor: "#eef3f6"
    readonly property color selectedBackground: Qt.rgba(0, 0, 0, 0.22)
    readonly property color hoverBackground: Qt.rgba(0, 0, 0, 0.1)
    readonly property color textColor: "#2b2b2b"
    readonly property color iconColor: "#1e73ff"
    readonly property color separatorColor: Qt.rgba(0, 0, 0, 0.16)
    readonly property color headerTextColor: "#1b1b1b"
    
    // Layout constants matching palette.py values
    readonly property int rowHeight: 36
    readonly property int leftPadding: 14
    readonly property int indentPerLevel: 22
    readonly property int iconSize: 24
    readonly property int iconTextGap: 10
    readonly property int branchIndicatorSize: 16
    readonly property int highlightMarginX: 6
    readonly property int highlightMarginY: 4
    readonly property int highlightRadius: 10
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        
        // Title
        Text {
            id: titleLabel
            Layout.fillWidth: true
            Layout.leftMargin: leftPadding
            text: "Basic Library"
            font.pixelSize: 15
            font.bold: true
            color: headerTextColor
        }
        
        // Tree list view
        ListView {
            id: treeView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            
            model: sidebarBridge && sidebarBridge.model ? sidebarBridge.model : null
            
            delegate: SidebarItem {
                width: treeView.width
                height: nodeType === 7 ? sidebar.rowHeight / 2 : sidebar.rowHeight  // Separator is smaller
                
                itemTitle: title
                itemNodeType: nodeType
                itemDepth: depth
                itemIsExpanded: isExpanded
                itemHasChildren: hasChildren
                itemIsSelectable: isSelectable
                itemIconName: iconName
                isSelected: ListView.isCurrentItem
                
                onClicked: {
                    if (isSelectable && sidebarBridge) {
                        treeView.currentIndex = index
                        sidebarBridge.selectItem(index)
                    }
                }
                
                onToggleExpansion: {
                    if (sidebarBridge) {
                        sidebarBridge.toggleExpansion(index)
                    }
                }
            }
            
            // Highlight current selection
            highlight: Rectangle {
                color: "transparent"  // SidebarItem handles its own highlight
            }
            highlightFollowsCurrentItem: true
            
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }
        }
    }
}
