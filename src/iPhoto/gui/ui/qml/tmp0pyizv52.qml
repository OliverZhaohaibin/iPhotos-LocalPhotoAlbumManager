
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1200
    height: 720
    title: "iPhoto"
    
    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal
        
        Sidebar {
            id: sidebar
            SplitView.preferredWidth: 220
            SplitView.minimumWidth: 180
            SplitView.maximumWidth: 350
        }
        
        Rectangle {
            id: contentArea
            SplitView.fillWidth: true
            color: "white"
            
            Text {
                anchors.centerIn: parent
                text: "Content"
            }
        }
    }
}
