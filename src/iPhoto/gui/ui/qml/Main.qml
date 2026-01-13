import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."  // Import local QML files

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1200
    height: 720
    title: "iPhoto"
    
    // Color palette matching the widget implementation
    readonly property color sidebarBackground: "#f5f5f5"
    readonly property color sidebarSelectedBackground: "#e0e0e0"
    readonly property color sidebarTextColor: "#2b2b2b"
    readonly property color sidebarIconColor: "#007AFF"
    readonly property color separatorColor: "#d0d0d0"
    
    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal
        
        // Sidebar
        Sidebar {
            id: sidebar
            SplitView.preferredWidth: 200
            SplitView.minimumWidth: 150
            SplitView.maximumWidth: 350
        }
        
        // Main content area (placeholder)
        Rectangle {
            id: contentArea
            SplitView.fillWidth: true
            color: "#ffffff"
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 20
                
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "📸 iPhoto QML"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#333333"
                }
                
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Select an album from the sidebar to view photos"
                    font.pixelSize: 16
                    color: "#666666"
                }
                
                Text {
                    id: statusText
                    Layout.alignment: Qt.AlignHCenter
                    text: sidebarBridge.hasLibrary ? "Library bound" : "No library bound"
                    font.pixelSize: 14
                    color: sidebarBridge.hasLibrary ? "#28a745" : "#dc3545"
                }
            }
        }
    }
    
    // Handle album selection
    Connections {
        target: sidebarBridge
        
        function onAlbumSelected(path) {
            statusText.text = "Selected album: " + path
        }
        
        function onAllPhotosSelected() {
            statusText.text = "Viewing: All Photos"
        }
        
        function onStaticNodeSelected(title) {
            statusText.text = "Viewing: " + title
        }
        
        function onBindLibraryRequested() {
            // In a full implementation, this would open a folder dialog
            statusText.text = "Library binding requested"
        }
    }
}
