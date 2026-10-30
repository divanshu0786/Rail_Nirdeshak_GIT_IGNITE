// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
    apiKey: "AIzaSyCf0ljc0-ppBcwhh8gXEeHAWP-wSQGLjmg",
    authDomain: "rail-nirdeshak.firebaseapp.com",
    projectId: "rail-nirdeshak",
    storageBucket: "rail-nirdeshak.firebasestorage.app",
    messagingSenderId: "724629020533",
    appId: "1:724629020533:web:e1f98f8e9bb42e37d9bd3c",
    measurementId: "G-PVVWQEPLXT"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);