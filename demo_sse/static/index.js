document.addEventListener("DOMContentLoaded", function () {
    var commandList = document.getElementById("commands");

// subscribe for messages
    var source = new EventSource('/stream');

// handle messages
    source.onmessage = function (event) {
        // Do something with the data:
        console.log(JSON.parse(event.data));
        // add to list
        var li = document.createElement("li");
        var t = document.createTextNode(JSON.parse(event.data)[0]);
        li.appendChild(t);
        commandList.appendChild(li);
    };
});
